# OJSDef ORM Models — Central Import Registry
# Semua model di-import di sini agar Alembic dan SQLAlchemy
# dapat mendeteksi seluruh tabel saat autogenerate migrasi.

from .base import Base
from .tenant import Tenant, TenantPlan
from .user import User, UserRole
from .ojs_target import OjsTarget
from .scan_job import ScanJob, ScanType, ScanStatus, RiskLevel
from .scan_finding import ScanFinding, FindingCategory, FindingSeverity
from .report import Report, ReportFormat
from .notification import Notification, NotificationChannel, NotificationType
from .audit_log import AuditLog

__all__ = [
    "Base",
    "Tenant", "TenantPlan",
    "User", "UserRole",
    "OjsTarget",
    "ScanJob", "ScanType", "ScanStatus", "RiskLevel",
    "ScanFinding", "FindingCategory", "FindingSeverity",
    "Report", "ReportFormat",
    "Notification", "NotificationChannel", "NotificationType",
    "AuditLog",
]
