from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.models.user import UserRole

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: UserRole = UserRole.admin_OJS
    is_active: bool = True

class UserCreate(UserBase):
    tenant_id: UUID
    password: str

class UserResponse(UserBase):
    id: UUID
    tenant_id: UUID
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
