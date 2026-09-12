from sqlalchemy import Column, String, Boolean, DateTime, Integer, Index, Text
from sqlalchemy.sql import func
from auth.database import AuthBase


class User(AuthBase):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, unique=True)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="viewer")
    department = Column(String, nullable=True)
    designation = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # Registration governance: an account must be approved by an admin before
    # it can access the protected portfolio. Self-registered accounts are
    # created with is_approved=False; migration default True keeps every
    # pre-existing legitimate/demo user approved (never locked out).
    is_approved = Column(Boolean, nullable=False, default=True, server_default="1")
    # Temporary-password enforcement: admin-created / reset accounts must pick a
    # permanent password at first login. Default False so existing users and
    # self-registered users who chose their own password are never forced.
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)

    # Brute-force protection state (see auth/lockout.py)
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_failed_login = Column(DateTime, nullable=True)
    locked_until = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_users_user_id", "user_id", unique=True),
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_role", "role"),
        Index("ix_users_is_active", "is_active"),
    )


class AuditLog(AuthBase):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    target_user_id = Column(String, nullable=True, index=True)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_audit_action_timestamp", "action", "timestamp"),
    )