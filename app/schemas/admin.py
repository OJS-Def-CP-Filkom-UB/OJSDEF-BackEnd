from pydantic import BaseModel, EmailStr
from app.schemas.auth import UserResponse, UserRole


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: UserRole
    tenant_id: str | None = None
    new_tenant_name: str | None = None
    telegram_username: str | None = None


class CreateUserResponse(UserResponse):
    """Response untuk POST /admin/users — temp_password hanya muncul sekali."""
    temp_password: str
    telegram_bot_deeplink: str = ""


class PatchUserRequest(BaseModel):
    is_active: bool | None = None
    role: UserRole | None = None


class CreateTenantRequest(BaseModel):
    name: str
    slug: str


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
