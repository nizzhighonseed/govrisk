from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from auth.database import get_auth_db
from auth.models import User
from auth.security import decode_token
from auth.audit import log_audit, ACTIONS

security = HTTPBearer()

PENDING_ACCESS_ERROR = "Account approval is required."
PASSWORD_CHANGE_REQUIRED_ERROR = "Password change required."


def _authenticate_user(
    credentials: HTTPAuthorizationCredentials,
    db: Session,
    allow_pending_password_change: bool = False,
) -> User:
    token = credentials.credentials
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    # Account state is always checked against the CURRENT database row on
    # every request, so an old/valid JWT can never bypass a deactivation, a
    # pending-approval state, or an outstanding password-change requirement.
    # The bearer token only proves authentication; authorization additionally
    # requires an active + approved account.
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    if not user.is_approved:
        log_audit(
            db,
            user,
            ACTIONS["ACCESS_DENIED_PENDING"],
            target_user_id=user.user_id,
            details="Access denied: account approval is required",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PENDING_ACCESS_ERROR,
        )
    if not allow_pending_password_change and user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PASSWORD_CHANGE_REQUIRED_ERROR,
        )
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_auth_db),
) -> User:
    return _authenticate_user(credentials, db, allow_pending_password_change=False)


def get_current_user_changing_password(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_auth_db),
) -> User:
    """Authenticated user for the SELF-SERVICE password-change endpoint.

    Identical to ``get_current_user`` except that an outstanding
    must_change_password flag does not block the request: the user must be
    able to reach the password-change flow. Only the password-change endpoint
    may depend on this. All other gates (active, approved) still apply.
    """
    return _authenticate_user(credentials, db, allow_pending_password_change=True)


def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return user


def require_admin(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_auth_db),
) -> User:
    if user.role != "admin":
        log_audit(
            db,
            user,
            ACTIONS["AUTHORIZATION_DENIED"],
            target_user_id=user.user_id,
            details="Denied an administrative action (role is not admin)",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def require_roles(*roles):
    def role_checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_auth_db),
    ) -> User:
        if user.role not in roles:
            allowed = ", ".join(roles)
            log_audit(
                db,
                user,
                ACTIONS["AUTHORIZATION_DENIED"],
                target_user_id=user.user_id,
                details=f"Denied an action requiring role(s): {allowed}",
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required roles: {allowed}",
            )
        return user

    return role_checker