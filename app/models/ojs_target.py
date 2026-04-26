import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from .base import Base


class OjsTarget(Base):
    __tablename__ = "ojs_targets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    url = Column(String(2048), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    verification_token = Column(String(255), nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    plugin_api_key = Column(Text, nullable=True)  # encrypted at app layer
    plugin_connected = Column(Boolean, nullable=False, default=False)
    ojs_version = Column(String(50), nullable=True)
    plugin_last_seen = Column(DateTime(timezone=True), nullable=True)
    last_scan_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relasi
    tenant = relationship("Tenant", back_populates="ojs_targets")
    creator = relationship("User", back_populates="created_targets", foreign_keys=[created_by])
    scan_jobs = relationship("ScanJob", back_populates="target", cascade="all, delete-orphan")
