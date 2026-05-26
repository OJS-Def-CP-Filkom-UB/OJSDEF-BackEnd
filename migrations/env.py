import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from app.config import get_settings
from app.models import Base

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata
settings = get_settings()


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(
            lambda conn: context.configure(conn=conn, target_metadata=target_metadata) or
                         context.begin_transaction() or context.run_migrations()
        )
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
