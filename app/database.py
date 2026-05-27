from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
from fastapi import Request
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession,
    expire_on_commit=False, autoflush=False,
)


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    import uuid as _uuid
    _uuid.UUID(tenant_id)  # raises ValueError if not a valid UUID
    # PostgreSQL SET command does NOT support bind parameters ($1) — embed UUID
    # directly as a literal. Safe because tenant_id is validated as a UUID above.
    await session.execute(
        text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
    )


async def get_db(request: Request):
    """Yield a DB session with RLS tenant context already applied.

    FastAPI auto-injects Request into Depends(get_db) — no changes needed
    in route handlers. tenant_id is set by jwt_middleware into request.state.
    """
    async with AsyncSessionLocal() as session:
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id:
            await set_tenant_context(session, tenant_id)
        yield session
