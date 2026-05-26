import uuid
import secrets
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from app.config import get_settings
from app.models import User

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _redis():
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _make_token(payload: dict, expire_delta: timedelta) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    exp = datetime.now(timezone.utc) + expire_delta
    data = {**payload, "jti": jti, "exp": exp}
    token = jwt.encode(data, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


async def create_tokens(user: User) -> dict:
    payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
    }
    access_token, _ = _make_token(
        payload, timedelta(minutes=settings.access_token_expire_minutes)
    )
    refresh_token, jti = _make_token(
        {"sub": str(user.id)},
        timedelta(days=settings.refresh_token_expire_days),
    )
    r = _redis()
    ttl = settings.refresh_token_expire_days * 86400
    await r.setex(f"refresh:{user.id}:{jti}", ttl, "1")
    await r.aclose()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


async def revoke_refresh_token(user_id: str, jti: str) -> None:
    r = _redis()
    await r.delete(f"refresh:{user_id}:{jti}")
    await r.aclose()


async def revoke_all_refresh_tokens(user_id: str) -> None:
    r = _redis()
    keys = await r.keys(f"refresh:{user_id}:*")
    if keys:
        await r.delete(*keys)
    await r.aclose()


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        return decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_role(*roles: str):
    async def dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return dependency
