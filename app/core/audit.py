# app/core/audit.py
import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


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
    """Record audit log. Fails silently — does not block the main request."""
    try:
        async with db.begin_nested():  # savepoint — rollback only affects this block
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
        await db.commit()  # persist the savepoint to the database
    except Exception as exc:
        logger.warning("create_audit_log failed silently: %s", exc)
