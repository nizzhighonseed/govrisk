from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from auth.database import get_auth_db
from auth.models import User
from auth.schemas import (
    UserResponse, ProfileUpdate, PasswordChange,
    UserRoleUpdate, UserStatusUpdate, AdminUserCreate, AdminUserUpdate,
    AdminCreateUserResponse, PasswordResetResponse, UserApprovalUpdate,
)
from auth.security import (
    hash_password,
    safe_verify_password,
    generate_id,
    generate_temporary_password,
)
from auth.dependencies import (
    get_current_user,
    get_current_user_changing_password,
    require_admin,
)
from auth.serializers import user_to_response
from auth.audit import log_audit, next_user_id, ACTIONS

router = APIRouter(prefix="/api/users", tags=["users"])


def _resolve_user(db: Session, identifier: str) -> User:
    user = db.query(User).filter(
        or_(User.user_id == identifier, User.id == identifier)
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/me", response_model=UserResponse)
def get_profile(user: User = Depends(get_current_user)):
    return user_to_response(user)


@router.put("/me", response_model=UserResponse)
def update_profile(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_auth_db),
):
    if data.fullName is not None:
        user.full_name = data.fullName
    if data.department is not None:
        user.department = data.department
    if data.designation is not None:
        user.designation = data.designation
    db.commit()
    db.refresh(user)
    return user_to_response(user)


@router.put("/me/password")
def change_password(
    data: PasswordChange,
    user: User = Depends(get_current_user_changing_password),
    db: Session = Depends(get_auth_db),
):
    """Change the caller's own password.

    Uses the permissive auth dependency so a user whose account is flagged
    ``must_change_password`` can still reach this endpoint to complete their
    first-login flow. ``must_change_password`` is cleared ONLY after the new
    password is verified to satisfy the existing policy and the fresh hash is
    successfully stored - a failed attempt leaves the flag untouched.
    """
    if not safe_verify_password(data.currentPassword, user.password_hash):
        log_audit(
            db,
            user,
            ACTIONS["PASSWORD_CHANGE_FAILED"],
            target_user_id=user.user_id,
            details="Password change rejected: current password is incorrect",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    new_hashed = hash_password(data.newPassword)
    user.password_hash = new_hashed
    user.must_change_password = False
    db.flush()
    log_audit(
        db,
        user,
        ACTIONS["PASSWORD_CHANGED"],
        target_user_id=user.user_id,
        details="Password changed",
    )
    db.commit()
    return {"message": "Password changed successfully"}


@router.get("/stats")
def get_users_stats(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
):
    total = db.query(User).count()
    active = db.query(User).filter(User.is_active == True).count()
    inactive = db.query(User).filter(User.is_active == False).count()
    admins = db.query(User).filter(User.role == "admin").count()
    officers = db.query(User).filter(User.role == "officer").count()
    analysts = db.query(User).filter(User.role == "analyst").count()
    viewers = db.query(User).filter(User.role == "viewer").count()
    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "admins": admins,
        "officers": officers,
        "analysts": analysts,
        "viewers": viewers,
    }


@router.get("")
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    approval: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    query = db.query(User)

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                User.full_name.ilike(like),
                User.email.ilike(like),
                User.user_id.ilike(like),
                User.designation.ilike(like),
            )
        )
    if role:
        query = query.filter(User.role == role)
    if status:
        if status == "active":
            query = query.filter(User.is_active == True)
        elif status == "inactive":
            query = query.filter(User.is_active == False)
    if approval:
        if approval == "pending":
            query = query.filter(User.is_approved == False)
        elif approval == "approved":
            query = query.filter(User.is_approved == True)
    if department:
        query = query.filter(User.department.ilike(f"%{department}%"))

    total = query.count()
    total_pages = (total + limit - 1) // limit if total else 0
    users = query.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "items": [user_to_response(u) for u in users],
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
    }


@router.post("", response_model=AdminCreateUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    data: AdminUserCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    # The temporary password is generated server-side with CSPRNG randomness
    # (auth.security.generate_temporary_password). Plaintext exists only in
    # this response, returned exactly once to the calling admin; it is never
    # stored, persisted, or audited.
    temp_password = generate_temporary_password()

    user = User(
        id=generate_id(),
        user_id=next_user_id(db),
        full_name=data.fullName,
        email=data.email,
        password_hash=hash_password(temp_password),
        role=data.role,
        department=data.department,
        designation=data.designation,
        is_active=data.isActive,
        # An admin-created account is authorised by the admin's explicit act;
        # the approval workflow only governs self-registered accounts.
        is_approved=True,
        # The user received a temporary password and MUST pick a permanent
        # one before they can use the portfolio.
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    log_audit(
        db,
        admin,
        ACTIONS["USER_CREATED"],
        target_user_id=user.user_id,
        details=f"Created new {data.role} account",
    )
    log_audit(
        db,
        admin,
        ACTIONS["TEMP_PASSWORD_GENERATED"],
        target_user_id=user.user_id,
        details="Generated temporary password; password change required at first login",
    )
    db.commit()
    db.refresh(user)

    response = AdminCreateUserResponse(
        **user_to_response(user).model_dump(),
        temporaryPassword=temp_password,
    )
    return response


@router.get("/{identifier}", response_model=UserResponse)
def get_user(
    identifier: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
):
    return user_to_response(_resolve_user(db, identifier))


@router.put("/{identifier}", response_model=UserResponse)
def admin_update_user(
    identifier: str,
    data: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
):
    user = _resolve_user(db, identifier)
    if data.fullName is not None:
        user.full_name = data.fullName
    if data.email is not None and data.email != user.email:
        if db.query(User).filter(User.email == data.email, User.id != user.id).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
        user.email = data.email
    if data.department is not None:
        user.department = data.department
    if data.designation is not None:
        user.designation = data.designation
    db.flush()
    log_audit(
        db,
        admin,
        ACTIONS["USER_UPDATED"],
        target_user_id=user.user_id,
        details="Updated user profile information",
    )
    db.commit()
    db.refresh(user)
    return user_to_response(user)


@router.patch("/{identifier}/role", response_model=UserResponse)
def update_user_role(
    identifier: str,
    data: UserRoleUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
):
    user = _resolve_user(db, identifier)
    if user.id == admin.id and data.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own admin role",
        )
    if user.role == "admin" and data.role != "admin":
        active_admins = db.query(User).filter(
            User.role == "admin", User.is_active == True, User.id != user.id
        ).count()
        if active_admins == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last active admin role",
            )
    old_role = user.role
    user.role = data.role
    db.flush()
    log_audit(
        db,
        admin,
        ACTIONS["ROLE_CHANGED"],
        target_user_id=user.user_id,
        details=f"Changed role from {old_role} to {data.role}",
    )
    db.commit()
    db.refresh(user)
    return user_to_response(user)


@router.patch("/{identifier}/status", response_model=UserResponse)
def update_user_status(
    identifier: str,
    data: UserStatusUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
):
    user = _resolve_user(db, identifier)
    if user.id == admin.id and not data.isActive:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )
    if user.role == "admin" and not data.isActive:
        active_admins = db.query(User).filter(
            User.role == "admin", User.is_active == True, User.id != user.id
        ).count()
        if active_admins == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate the last active admin",
            )
    user.is_active = data.isActive
    db.flush()
    log_audit(
        db,
        admin,
        ACTIONS["USER_ACTIVATED"] if data.isActive else ACTIONS["USER_DEACTIVATED"],
        target_user_id=user.user_id,
        details="Activated account" if data.isActive else "Deactivated account",
    )
    db.commit()
    db.refresh(user)
    return user_to_response(user)


@router.patch("/{identifier}/approval", response_model=UserResponse)
def update_user_approval(
    identifier: str,
    data: UserApprovalUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
):
    """Approve or reject (unapprove) a user's portfolio access.

    Admin-only. A user can never change their own approval state, and the last
    active admin can never be unapproved (mirrors the role/status guards).
    Approval only flips is_approved - deactivated accounts stay blocked until
    an admin reactivates them.
    """
    user = _resolve_user(db, identifier)
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own approval state",
        )
    if user.role == "admin" and not data.isApproved:
        other_active_admins = db.query(User).filter(
            User.role == "admin",
            User.is_active == True,
            User.is_approved == True,
            User.id != user.id,
        ).count()
        if other_active_admins == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot unapprove the last active admin",
            )
    user.is_approved = data.isApproved
    db.flush()
    log_audit(
        db,
        admin,
        ACTIONS["USER_APPROVED"] if data.isApproved else ACTIONS["USER_REJECTED"],
        target_user_id=user.user_id,
        details="Approved account" if data.isApproved else "Rejected account approval",
    )
    db.commit()
    db.refresh(user)
    return user_to_response(user)


@router.post("/{identifier}/reset-password", response_model=PasswordResetResponse)
def reset_user_password(
    identifier: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_auth_db),
):
    user = _resolve_user(db, identifier)
    # New temporary password is generated server-side with CSPRNG randomness
    # (auth.security.generate_temporary_password) and returned exactly once to
    # the admin in this response. It is never stored in plaintext and the
    # account must change it at next login, invalidating any previously known
    # password.
    temp_password = generate_temporary_password()
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    db.flush()
    log_audit(
        db,
        admin,
        ACTIONS["PASSWORD_RESET"],
        target_user_id=user.user_id,
        details="Password reset; temporary password issued; change required at next login",
    )
    log_audit(
        db,
        admin,
        ACTIONS["TEMP_PASSWORD_GENERATED"],
        target_user_id=user.user_id,
        details="Generated temporary password; password change required at next login",
    )
    db.commit()
    return PasswordResetResponse(
        message="Temporary password generated",
        temporaryPassword=temp_password,
    )