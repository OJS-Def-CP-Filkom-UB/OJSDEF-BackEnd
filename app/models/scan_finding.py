import uuid
from sqlalchemy import String, Float, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from app.models.base import Base, TimestampMixin


class ScanFinding(Base, TimestampMixin):
    __tablename__ = "scan_findings"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("scan_jobs.id"), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    remediation: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    cvss_score: Mapped[float] = mapped_column(Float, nullable=False)
    cve_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    owasp_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_false_positive: Mapped[bool] = mapped_column(Boolean, default=False)
