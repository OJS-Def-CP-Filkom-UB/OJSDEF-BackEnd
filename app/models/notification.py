import uuid
from sqlalchemy import Column, Text, Boolean, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import enum
from .base import Base


class NotificationChannel(str, enum.Enum):
    email = "email"
    telegram = "telegram"


class NotificationType(str, enum.Enum):
    critical_alert = "critical_alert"
    scan_summary = "scan_summary"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(Enum(NotificationChannel, name="notification_channel", create_constraint=False, native_enum=True), nullable=False)
    type = Column(Enum(NotificationType, name="notification_type", create_constraint=False, native_enum=True), nullable=False)
    payload = Column(JSONB, nullable=True)
    is_sent = Column(Boolean, nullable=False, default=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    error_log = Column(Text, nullable=True)

    # Relasi
    job = relationship("ScanJob", back_populates="notifications")
    user = relationship("User", back_populates="notifications")
