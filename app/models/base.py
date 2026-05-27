import uuid
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    # Map Python datetime → TIMESTAMP WITH TIME ZONE for all models globally.
    # asyncpg requires timezone-aware datetimes for TIMESTAMPTZ columns;
    # without this override, Mapped[datetime] defaults to DateTime(timezone=False)
    # which causes DataError: "can't subtract offset-naive and offset-aware datetimes".
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
