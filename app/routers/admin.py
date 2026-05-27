import uuid
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import User, Tenant
from app.schemas.admin import (
    CreateUserRequest, CreateUserResponse, PatchUserRequest,
    CreateTenantRequest, TenantResponse,
)
from app.services.auth import require_role, hash_password

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
_saas = Depends(require_role("saas_admin"))


@router.post("/users", response_model=CreateUserResponse, status_code=201, dependencies=[_saas])
async def create_user(body: CreateUserRequest, db: AsyncSession = Depends(get_db)):
    temp_password = secrets.token_urlsafe(12)
    tid = uuid.UUID(body.tenant_id) if body.tenant_id else None
    if not tid:
        result = await db.execute(select(Tenant).where(Tenant.slug == "default"))
        tenant = result.scalar_one_or_none()
        tid = tenant.id if tenant else None
    user = User(
        id=uuid.uuid4(), tenant_id=tid,
        email=body.email, full_name=body.full_name, role=body.role,
        hashed_password=hash_password(temp_password),
        must_change_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    # temp_password is returned in plaintext exactly ONCE here.
    # It is never stored in plaintext — only as a bcrypt hash in hashed_password.
    return CreateUserResponse(
        id=str(user.id), email=user.email, full_name=user.full_name,
        role=user.role, must_change_password=user.must_change_password,
        notif_email=user.notif_email, notif_telegram=user.notif_telegram,
        telegram_chat_id=user.telegram_chat_id,
        temp_password=temp_password,
    )


@router.get("/users", dependencies=[_saas])
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [
        {"id": str(u.id), "email": u.email, "role": u.role, "is_active": u.is_active}
        for u in users
    ]


@router.patch("/users/{user_id}", dependencies=[_saas])
async def patch_user(
    user_id: uuid.UUID,
    body: PatchUserRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User tidak ditemukan")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(user, field, val)
    await db.commit()
    return {"id": str(user.id), "is_active": user.is_active, "role": user.role}


@router.delete("/users/{user_id}", status_code=204, dependencies=[_saas])
async def delete_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User tidak ditemukan")
    await db.delete(user)
    await db.commit()


@router.post("/tenants", response_model=TenantResponse, status_code=201, dependencies=[_saas])
async def create_tenant(body: CreateTenantRequest, db: AsyncSession = Depends(get_db)):
    tenant = Tenant(id=uuid.uuid4(), name=body.name, slug=body.slug)
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return TenantResponse(id=str(tenant.id), name=tenant.name, slug=tenant.slug, is_active=tenant.is_active)


@router.get("/tenants", dependencies=[_saas])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant))
    return [
        {"id": str(t.id), "name": t.name, "slug": t.slug, "is_active": t.is_active}
        for t in result.scalars()
    ]
