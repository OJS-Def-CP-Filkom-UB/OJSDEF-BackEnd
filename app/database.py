from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker,
)
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


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    import uuid as _uuid
    _uuid.UUID(tenant_id)  # raises ValueError if not a valid UUID
    await session.execute(
        text("SET LOCAL app.current_tenant_id = :tid"),
        {"tid": tenant_id},
    )
