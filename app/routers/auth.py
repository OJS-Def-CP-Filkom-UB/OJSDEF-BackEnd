from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
import redis.asyncio as aioredis
from app.database import get_db
from app.models import User
from app.schemas.auth import (
    LoginRequest, TokenResponse, RefreshRequest,
    UpdateProfileRequest, ChangePasswordRequest, UserResponse,
)
from app.services.auth import (
    authenticate_user, create_tokens, decode_access_token,
    revoke_refresh_token, revoke_all_refresh_tokens,
    hash_password, verify_password, get_current_user, require_role,
)
from app.config import get_settings
from app.core.audit import create_audit_log

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings = get_settings()


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(db, body.email, body.password)
    if not user:
        await create_audit_log(
            db,
            user_id=None,
            user_email=body.email,
            tenant_id=None,
            action="user.login_failed",
            resource_type="auth",
            details={"attempted_email": body.email},
        )
        raise HTTPException(status_code=401, detail="Credensial tidak valid")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akun dinonaktifkan")
    tokens = await create_tokens(user)
    await create_audit_log(
        db,
        user_id=str(user.id),
        user_email=user.email,
        tenant_id=str(user.tenant_id),
        action="user.login",
        resource_type="auth",
        resource_id=str(user.id),
    )
    return TokenResponse(**tokens, must_change_password=user.must_change_password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_access_token(body.refresh_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token tidak valid")
    # Verify token exists in Redis (not revoked)
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    exists = await r.exists(f"refresh:{payload['sub']}:{payload['jti']}")
    await r.aclose()
    if not exists:
        raise HTTPException(status_code=401, detail="Refresh token tidak valid atau sudah digunakan")
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User tidak ditemukan")
    await revoke_refresh_token(str(user.id), payload["jti"])
    tokens = await create_tokens(user)
    return TokenResponse(**tokens)


@router.post("/logout", status_code=204)
async def logout(
    body: RefreshRequest | None = Body(default=None),
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body and body.refresh_token:
        try:
            payload = decode_access_token(body.refresh_token)
            await revoke_refresh_token(payload["sub"], payload["jti"])
        except JWTError:
            pass
    await create_audit_log(
        db,
        user_id=current.get("sub"),
        user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"),
        action="user.logout",
        resource_type="auth",
    )


@router.get("/me", response_model=UserResponse)
async def me(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current["sub"]))
    user = result.scalar_one()
    return UserResponse(
        id=str(user.id), email=user.email, full_name=user.full_name,
        role=user.role, must_change_password=user.must_change_password,
        notif_email=user.notif_email, notif_telegram=user.notif_telegram,
        telegram_chat_id=user.telegram_chat_id,
    )


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UpdateProfileRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current["sub"]))
    user = result.scalar_one()
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(user, field, val)
    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=str(user.id), email=user.email, full_name=user.full_name,
        role=user.role, must_change_password=user.must_change_password,
        notif_email=user.notif_email, notif_telegram=user.notif_telegram,
        telegram_chat_id=user.telegram_chat_id,
    )


@router.put("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current["sub"]))
    user = result.scalar_one()
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Password lama salah")
    user.hashed_password = hash_password(body.new_password)
    user.must_change_password = False
    await db.commit()
    await revoke_all_refresh_tokens(str(user.id))
    await create_audit_log(
        db,
        user_id=str(user.id),
        user_email=user.email,
        tenant_id=current.get("tenant_id"),
        action="user.password_changed",
        resource_type="auth",
        resource_id=str(user.id),
    )
