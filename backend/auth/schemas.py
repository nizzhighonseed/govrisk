from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserRegister(BaseModel):
    fullName: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    department: Optional[str] = None
    designation: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    userId: str
    fullName: str
    email: str
    role: str
    department: Optional[str] = None
    designation: Optional[str] = None
    isActive: bool
    isApproved: bool
    mustChangePassword: bool
    createdAt: str
    updatedAt: str
    lastLogin: Optional[str] = None


class AuthResponse(BaseModel):
    accessToken: str
    refreshToken: str
    user: UserResponse


class TokenRefresh(BaseModel):
    refreshToken: str


class ProfileUpdate(BaseModel):
    fullName: Optional[str] = Field(None, min_length=1, max_length=100)
    department: Optional[str] = None
    designation: Optional[str] = None


class PasswordChange(BaseModel):
    currentPassword: str
    newPassword: str = Field(..., min_length=6, max_length=128)


class UserRoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(admin|officer|analyst|viewer)$")


class UserStatusUpdate(BaseModel):
    isActive: bool


class AdminUserCreate(BaseModel):
    fullName: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    role: str = Field(..., pattern="^(admin|officer|analyst|viewer)$")
    department: Optional[str] = None
    designation: Optional[str] = None
    isActive: bool = True
    # NOTE: no temporaryPassword field. The server generates a
    # cryptographically secure temporary password via `secrets` and returns it
    # exactly once to the calling admin. Human-chosen or client-supplied
    # temporary passwords are never accepted.


class AdminCreateUserResponse(UserResponse):
    temporaryPassword: str


class AdminUserUpdate(BaseModel):
    fullName: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    department: Optional[str] = None
    designation: Optional[str] = None


class UserApprovalUpdate(BaseModel):
    isApproved: bool


class PasswordResetResponse(BaseModel):
    message: str
    temporaryPassword: str