from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from auth.database import get_auth_db
from auth.models import User
from auth.schemas import (
    UserRegister, UserLogin, UserResponse, AuthResponse,
    TokenRefresh,
)
from auth.security import (
    DUMMY_PASSWORD_HASH, generate_id, hash_password, safe_verify_password,
    create_access_token, create_refresh_token, decode_token,
)
import auth.lockout as lockout
import auth.rate_limit as rate_limit
from auth.dependencies import get_current_user_changing_password
from auth.serializers import user_to_response
from auth.audit import log_audit, next_user_id, ACTIONS

GENERIC_AUTH_ERROR = "Invalid email or password"
GENERIC_LOCK_MESSAGE = rate_limit.GENERIC_LIMIT_MESSAGE

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _pending_placeholder_response(email: str) -> AuthResponse:
    """Byte-identical-looking registration response for a duplicate email.

    Returning the same 201 shape (no 409, no "email already exists") means the
    public registration endpoint does not betray whether a mailbox already has
    an account. The tokens reference a random, non-existent subject so they are
    unusable - they exist only to keep the response indistinguishable from a
    genuine pending registration. The submitted email is echoed back because it
    is the caller's own input.
    """
    now = datetime.now(timezone.utc).isoformat()
    user = UserResponse(
        id="",
        userId="",
        fullName="Pending User",
        email=email,
        role="viewer",
        department=None,
        designation=None,
        isActive=True,
        isApproved=False,
        mustChangePassword=False,
        createdAt=now,
        updatedAt=now,
        lastLogin=None,
    )
    phantom = f"pending-{generate_id()}"
    return AuthResponse(
        accessToken=create_access_token(phantom, "viewer"),
        refreshToken=create_refresh_token(phantom),
        user=user,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(data: UserRegister, request: Request, db: Session = Depends(get_auth_db)):
    try:
        rate_limit.enforce(
            request,
            f"register:ip:{rate_limit.client_ip(request)}",
        )
    except HTTPException as exc:
        log_audit(
            db, None, ACTIONS["RATE_LIMITED"],
            details="Account registration rejected: rate limit exceeded",
        )
        db.commit()
        raise exc

    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        # No account-enumeration oracle: act as though the registration was
        # accepted, identical to a real pending submission.
        return _pending_placeholder_response(data.email)

    user = User(
        id=generate_id(),
        user_id=next_user_id(db),
        full_name=data.fullName,
        email=data.email,
        password_hash=hash_password(data.password),
        role="viewer",
        department=data.department,
        designation=data.designation,
        is_active=True,
        # Self-registration never grants portfolio access until an admin
        # explicitly approves the account.
        is_approved=False,
        # Self-registered users chose their own password, so they are never
        # forced through the temporary-password change flow.
        must_change_password=False,
    )
    db.add(user)
    db.flush()
    log_audit(
        db,
        user,
        ACTIONS["REGISTERED"],
        target_user_id=user.user_id,
        details="Self-registered account",
    )
    db.commit()
    db.refresh(user)

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id)

    return AuthResponse(
        accessToken=access_token,
        refreshToken=refresh_token,
        user=user_to_response(user),
    )


@router.post("/login", response_model=AuthResponse)
def login(data: UserLogin, request: Request, db: Session = Depends(get_auth_db)):
    email = data.email.strip().lower()
    now = lockout.utcnow_naive()
    user = db.query(User).filter(User.email == email).first()

    # Request-level throttle FIRST: per client IP and per normalized email,
    # covering unknown accounts too (defends against password spraying and
    # against hammering a single email from many IPs).
    try:
        rate_limit.enforce(
            request,
            f"login:ip:{rate_limit.client_ip(request)}",
            f"login:email:{rate_limit.hash_key(email)}",
        )
    except HTTPException as exc:
        if user is not None:
            log_audit(
                db, user, ACTIONS["LOGIN_FAILED"],
                target_user_id=user.user_id,
                details="Login rejected: request rate limit exceeded",
            )
        db.commit()
        raise exc

    # Temporary account lockout (persisted on the user row). Correct
    # passwords are also rejected while locked so a lockout can never be
    # bypassed by simply waiting for the right credential.
    if user is not None and lockout.is_locked(user, now):
        log_audit(
            db, user, ACTIONS["LOGIN_FAILED"],
            target_user_id=user.user_id,
            details="Login rejected: account temporarily locked",
        )
        db.commit()
        retry_after = max(1, int((user.locked_until - now).total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=GENERIC_LOCK_MESSAGE,
            headers={"Retry-After": str(retry_after)},
        )

    if user is None:
        # Burn the same bcrypt cost as a real account so timing does not
        # reveal whether the email exists.
        safe_verify_password(data.password, DUMMY_PASSWORD_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GENERIC_AUTH_ERROR,
        )

    if not safe_verify_password(data.password, user.password_hash):
        newly_locked = lockout.register_failed_attempt(db, user, now)
        log_audit(
            db, user, ACTIONS["LOGIN_FAILED"],
            target_user_id=user.user_id,
            details="Failed login attempt (invalid password)",
        )
        if newly_locked:
            log_audit(
                db, user, ACTIONS["ACCOUNT_LOCKED"],
                target_user_id=user.user_id,
                details="Account temporarily locked after repeated failures",
            )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GENERIC_AUTH_ERROR,
        )

    if not user.is_active:
        log_audit(
            db,
            user,
            ACTIONS["LOGIN_FAILED"],
            target_user_id=user.user_id,
            details="Login rejected: account deactivated",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    lockout.clear_failed_attempts(db, user)
    user.last_login = datetime.now(timezone.utc)
    log_audit(db, user, ACTIONS["LOGIN_SUCCESS"], target_user_id=user.user_id, details="Successful login")
    db.commit()

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id)

    return AuthResponse(
        accessToken=access_token,
        refreshToken=refresh_token,
        user=user_to_response(user),
    )


@router.post("/refresh", response_model=AuthResponse)
def refresh_token(data: TokenRefresh, request: Request, db: Session = Depends(get_auth_db)):
    try:
        rate_limit.enforce(
            request,
            f"refresh:ip:{rate_limit.client_ip(request)}",
            f"refresh:token:{rate_limit.hash_key(data.refreshToken)}",
        )
    except HTTPException as exc:
        log_audit(
            db, None, ACTIONS["RATE_LIMITED"],
            details="Token refresh rejected: rate limit exceeded",
        )
        db.commit()
        raise exc

    payload = decode_token(data.refreshToken)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    access_token = create_access_token(user.id, user.role)
    refresh_token_new = create_refresh_token(user.id)

    return AuthResponse(
        accessToken=access_token,
        refreshToken=refresh_token_new,
        user=user_to_response(user),
    )


@router.post("/logout")
def logout(
    user: User = Depends(get_current_user_changing_password),
    db: Session = Depends(get_auth_db),
):
    log_audit(db, user, ACTIONS["LOGOUT"], target_user_id=user.user_id, details="Logged out")
    db.commit()
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user_changing_password)):
    # Uses the password-change-permitting dependency so an account flagged
    # must_change_password can still bootstrap its session/profile and be
    # redirected to the first-login change flow. Identity endpoints never
    # bypass the active/approved gates, and the must-change requirement is
    # still enforced on every portfolio and action endpoint.
    return user_to_response(user)