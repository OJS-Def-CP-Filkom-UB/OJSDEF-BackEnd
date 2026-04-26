import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from .base import Base


class UserRole(str, enum.Enum):
    admin_OJS = "admin_OJS"
    admin_SaaS = "admin_SaaS"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole, name="user_role", create_constraint=False, native_enum=True), nullable=False, default=UserRole.admin_OJS)
    is_active = Column(Boolean, nullable=False, default=True)
    notif_email = Column(Boolean, nullable=False, default=True)
    notif_telegram = Column(Boolean, nullable=False, default=False)
    telegram_chat_id = Column(String(255), nullable=True)
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relasi
    tenant = relationship("Tenant", back_populates="users")
    created_targets = relationship("OjsTarget", back_populates="creator", foreign_keys="OjsTarget.created_by")
    initiated_jobs = relationship("ScanJob", back_populates="initiator", foreign_keys="ScanJob.initiated_by")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")
