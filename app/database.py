from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
from fastapi import Request
from app.config import get_settings

settings = get_settings()

# Runtime engine — menggunakan role ojsdef_app (non-owner, kena FORCE RLS)
engine = create_async_engine(
    settings.database_url_app,
    echo=settings.environment == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession,
    expire_on_commit=False, autoflush=False,
)

# Owner engine — menggunakan role ojsdef (table owner, bypass RLS)
# Dipakai oleh: Celery workers, auth endpoints (login/refresh)
owner_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

OwnerSessionLocal = async_sessionmaker(
    owner_engine, class_=AsyncSession,
    expire_on_commit=False, autoflush=False,
)


@asynccontextmanager
async def make_worker_session():
    """Buat fresh async engine + session untuk Celery task.

    Mencegah RuntimeError 'Future attached to a different loop' yang terjadi
    saat engine module-level dipakai ulang lintas asyncio.run() calls di
    Celery prefork workers. Pakai owner engine — bypass RLS secara legitimate.
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


async def set_tenant_context(session: AsyncSession, tenant_id: str, role: str) -> None:
    """Set PostgreSQL session-level variables untuk RLS tenant isolation.

    Menggunakan SET (bukan SET LOCAL) agar context bertahan setelah commit().
    Caller wajib reset ke '' setelah selesai (lihat get_db finally block).
    """
    import uuid as _uuid
    _uuid.UUID(tenant_id)  # validasi format UUID — raise ValueError jika invalid
    await session.execute(text(f"SET app.current_tenant_id = '{tenant_id}'"))
    await session.execute(text(f"SET app.current_role = '{role}'"))


async def get_db(request: Request):
    """Yield DB session dengan RLS tenant context (session-level SET).

    Context di-reset ke '' di finally block sebelum koneksi dikembalikan ke pool
    agar tidak ada tenant context yang bocor ke request berikutnya.
    """
    async with AsyncSessionLocal() as session:
        tenant_id = getattr(request.state, "tenant_id", None)
        role = getattr(request.state, "role", None)
        if tenant_id and role:
            await set_tenant_context(session, tenant_id, role)
        try:
            yield session
        finally:
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.current_role = ''"))


async def get_auth_db():
    """Yield owner DB session untuk auth endpoints (login, refresh).

    Login belum punya JWT sehingga tidak ada tenant context yang bisa di-set.
    Owner session bypass RLS agar user lookup by email bisa berjalan.
    """
    async with OwnerSessionLocal() as session:
        yield session
