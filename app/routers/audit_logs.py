import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from app.database import get_db
from app.models.audit_log import AuditLog
from app.services.auth import require_role

router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit-logs"])
_saas = Depends(require_role("saas_admin"))


class AuditLogResponse(BaseModel):
    id: str
    user_email: str
    tenant_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    details: dict | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    per_page: int


@router.get("", response_model=AuditLogListResponse, dependencies=[_saas])
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None),
    user_email: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        q = q.where(AuditLog.action == action)
    if user_email:
        q = q.where(AuditLog.user_email.ilike(f"%{user_email}%"))
    if tenant_id:
        try:
            q = q.where(AuditLog.tenant_id == uuid.UUID(tenant_id))
        except ValueError:
            raise HTTPException(422, "tenant_id harus berupa UUID valid")
    if date_from:
        q = q.where(AuditLog.created_at >= date_from)
    if date_to:
        q = q.where(AuditLog.created_at <= date_to)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()
    result = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    items = result.scalars().all()

    return AuditLogListResponse(
        items=[AuditLogResponse(
            id=str(log.id), user_email=log.user_email,
            tenant_id=str(log.tenant_id) if log.tenant_id else None,
            action=log.action, resource_type=log.resource_type,
            resource_id=log.resource_id, details=log.details, created_at=log.created_at,
        ) for log in items],
        total=total, page=page, per_page=per_page,
    )
