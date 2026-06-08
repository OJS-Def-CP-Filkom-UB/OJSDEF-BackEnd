from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
from sqlalchemy.orm import Session
from fastapi import Request
from app.config import get_settings

settings = get_settings()

# Runtime engine — menggunakan role ojsdef_app (non-owner, kena RLS secara default)
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


@event.listens_for(Session, "after_begin")
def _reapply_tenant_context(session, transaction, connection):
    """Re-issue RLS GUC SET pada setiap awal transaksi baru di koneksi manapun.

    SQLAlchemy melepas koneksi fisik ke pool setelah tiap commit() dan bisa
    checkout koneksi BERBEDA untuk transaksi berikutnya dalam session yang sama
    (mis. db.commit() lalu db.refresh()). Karena `SET app.current_tenant_id`
    terikat ke koneksi fisik (bukan ke AsyncSession), transaksi baru di koneksi
    lain akan punya GUC kosong → baris yang baru di-commit jadi tidak terlihat
    oleh RLS (`Could not refresh instance`). Listener ini menjamin GUC selalu
    di-set ulang di awal setiap transaksi, di koneksi manapun ia berjalan.
    """
    ctx = session.info.get("tenant_context")
    if ctx:
        tenant_id, role = ctx
        connection.exec_driver_sql(f"SET app.current_tenant_id = '{tenant_id}'")
        connection.exec_driver_sql(f"SET app.user_role = '{role}'")


async def set_tenant_context(session: AsyncSession, tenant_id: str, role: str) -> None:
    """Set PostgreSQL session-level variables untuk RLS tenant isolation.

    Selain SET langsung di koneksi aktif, context disimpan di `session.info`
    sehingga listener `_reapply_tenant_context` bisa menerapkannya kembali di
    setiap transaksi baru — termasuk di koneksi fisik berbeda setelah commit().
    Caller wajib reset ke '' setelah selesai (lihat get_db finally block).
    """
    import uuid as _uuid
    _uuid.UUID(tenant_id)  # validasi format UUID — raise ValueError jika invalid
    await session.execute(text(f"SET app.current_tenant_id = '{tenant_id}'"))
    await session.execute(text(f"SET app.user_role = '{role}'"))
    session.info["tenant_context"] = (tenant_id, role)


async def get_db(request: Request):
    """Yield DB session dengan RLS tenant context (session-level SET).

    Context di-reset ke '' di finally block sebelum koneksi dikembalikan ke pool
    agar tidak ada tenant context yang bocor ke request berikutnya. `tenant_context`
    dihapus dari session.info LEBIH DULU agar listener tidak menerapkan kembali
    context lama saat statement reset di bawah memicu transaksi baru.
    """
    async with AsyncSessionLocal() as session:
        tenant_id = getattr(request.state, "tenant_id", None)
        role = getattr(request.state, "role", None)
        if tenant_id and role:
            await set_tenant_context(session, tenant_id, role)
        try:
            yield session
        finally:
            session.info.pop("tenant_context", None)
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.user_role = ''"))


async def get_auth_db():
    """Yield owner DB session untuk auth endpoints (login, refresh).

    Login belum punya JWT sehingga tidak ada tenant context yang bisa di-set.
    Owner session bypass RLS agar user lookup by email bisa berjalan.
    """
    async with OwnerSessionLocal() as session:
        yield session
