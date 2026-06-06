from typing import Literal
from pydantic import BaseModel, EmailStr

UserRole = Literal["admin_ojs", "saas_admin", "viewer"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    notif_email: bool | None = None
    notif_telegram: bool | None = None
    telegram_chat_id: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    must_change_password: bool
    notif_email: bool
    notif_telegram: bool
    telegram_chat_id: str | None = None
    telegram_username: str | None = None
