import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from app.models.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, server_default="unknown")
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
