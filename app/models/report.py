import uuid
from sqlalchemy import Column, Text, Integer, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from .base import Base


class ReportFormat(str, enum.Enum):
    pdf = "pdf"
    json = "json"
    html = "html"


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    format = Column(Enum(ReportFormat, name="report_format", create_constraint=False, native_enum=True), nullable=False)
    file_url = Column(Text, nullable=False)  # MinIO object path
    file_size_bytes = Column(Integer, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relasi
    job = relationship("ScanJob", back_populates="reports")
