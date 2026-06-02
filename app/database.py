from contextlib import asynccontextmanager

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


@asynccontextmanager
async def make_worker_session():
    """Buat fresh async engine + session untuk Celery task.

    Mencegah RuntimeError 'Future attached to a different loop' yang terjadi
    saat engine module-level dipakai ulang lintas asyncio.run() calls di
    Celery prefork workers.
    """
    worker_engine = create_async_engine(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    SessionLocal = async_sessionmaker(
        worker_engine, class_=AsyncSession,
        expire_on_commit=False, autoflush=False,
    )
    try:
        async with SessionLocal() as session:
            yield session
    finally:
        await worker_engine.dispose()


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    import uuid as _uuid
    _uuid.UUID(tenant_id)
    await session.execute(
        text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
    )


async def get_db(request: Request):
    """Yield a DB session with RLS tenant context already applied."""
    async with AsyncSessionLocal() as session:
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id:
            await set_tenant_context(session, tenant_id)
        yield session
