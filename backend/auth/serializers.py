from auth.models import User
from auth.schemas import UserResponse


def user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        userId=user.user_id,
        fullName=user.full_name,
        email=user.email,
        role=user.role,
        department=user.department,
        designation=user.designation,
        isActive=user.is_active,
        isApproved=user.is_approved,
        mustChangePassword=user.must_change_password,
        createdAt=user.created_at.isoformat() if user.created_at else "",
        updatedAt=user.updated_at.isoformat() if user.updated_at else "",
        lastLogin=user.last_login.isoformat() if user.last_login else None,
    )