# app/core/audit.py
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AuditLog


async def create_audit_log(
    db: AsyncSession,
    user_id: str | None,
    user_email: str,
    tenant_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Record audit log. Gagal silently — tidak block request utama."""
    try:
        log = AuditLog(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
            user_id=uuid.UUID(user_id) if user_id else None,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        db.add(log)
        await db.commit()
    except Exception:
        await db.rollback()
