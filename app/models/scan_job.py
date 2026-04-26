import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, Numeric, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from .base import Base


class ScanType(str, enum.Enum):
    internal = "internal"
    external = "external"
    full = "full"


class ScanStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id = Column(UUID(as_uuid=True), ForeignKey("ojs_targets.id", ondelete="CASCADE"), nullable=False, index=True)
    initiated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    scan_type = Column(Enum(ScanType, name="scan_type", create_constraint=False, native_enum=True), nullable=False)
    status = Column(Enum(ScanStatus, name="scan_status", create_constraint=False, native_enum=True), nullable=False, default=ScanStatus.queued)
    celery_task_id = Column(String(255), nullable=True)
    overall_score = Column(Numeric(5, 2), nullable=True)  # 0.00 - 100.00
    risk_level = Column(Enum(RiskLevel, name="risk_level", create_constraint=False, native_enum=True), nullable=True)
    total_findings = Column(Integer, nullable=False, default=0)
    critical_count = Column(Integer, nullable=False, default=0)
    high_count = Column(Integer, nullable=False, default=0)
    medium_count = Column(Integer, nullable=False, default=0)
    low_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relasi
    target = relationship("OjsTarget", back_populates="scan_jobs")
    initiator = relationship("User", back_populates="initiated_jobs", foreign_keys=[initiated_by])
    findings = relationship("ScanFinding", back_populates="job", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="job", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="job", cascade="all, delete-orphan")
