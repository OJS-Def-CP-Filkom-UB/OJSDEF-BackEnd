import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, Numeric, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from .base import Base


class FindingCategory(str, enum.Enum):
    internal = "internal"
    external = "external"


class FindingSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ScanFinding(Base):
    __tablename__ = "scan_findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_type = Column(String(255), nullable=False)
    category = Column(Enum(FindingCategory, name="finding_category", create_constraint=False, native_enum=True), nullable=False)
    severity = Column(Enum(FindingSeverity, name="finding_severity", create_constraint=False, native_enum=True), nullable=False)
    cvss_score = Column(Numeric(4, 2), nullable=True)  # 0.0 - 10.0
    cve_id = Column(String(50), nullable=True)
    owasp_category = Column(String(100), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    affected_path = Column(Text, nullable=True)
    evidence = Column(Text, nullable=True)
    remediation = Column(Text, nullable=True)
    is_false_positive = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relasi
    job = relationship("ScanJob", back_populates="findings")
