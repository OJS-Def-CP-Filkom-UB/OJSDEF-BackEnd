from pydantic import BaseModel, EmailStr


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: str
    tenant_id: str | None = None


class PatchUserRequest(BaseModel):
    is_active: bool | None = None
    role: str | None = None


class CreateTenantRequest(BaseModel):
    name: str
    slug: str


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
