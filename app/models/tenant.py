import uuid
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from .base import Base

class TenantPlan(str, enum.Enum):
    free = "free"
    pro = "pro"
    enterprise = "enterprise"

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    plan = Column(Enum(TenantPlan), nullable=False, default=TenantPlan.free)
    api_quota = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relasi ke Users
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
