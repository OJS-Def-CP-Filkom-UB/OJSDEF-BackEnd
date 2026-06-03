import uuid
from datetime import datetime
from sqlalchemy import DateTime, String, Boolean, Text, ForeignKey, false as sa_false
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin


class OJSTarget(Base, TimestampMixin):
    __tablename__ = "ojs_targets"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plugin_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    plugin_last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ojs_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Plugin connection fields — populated by heartbeat + probe cycle
    trigger_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    probe_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    connection_mode: Mapped[str | None] = mapped_column(String(20), nullable=True, default="unknown")
    # Heartbeat mode: stores job waiting for next heartbeat trigger; cleared after callback received
    pending_scan_job_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # Opt-in: paksa mode heartbeat untuk OJS di balik firewall (lewati pre-flight probe)
    force_heartbeat: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa_false())
