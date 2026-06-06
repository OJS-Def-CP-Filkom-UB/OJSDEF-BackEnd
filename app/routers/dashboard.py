import uuid
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import redis.asyncio as aioredis
from app.database import get_db
from app.models import ScanJob, OJSTarget, ScanFinding
from app.services.auth import get_current_user
from app.config import get_settings

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])
settings = get_settings()


async def _build_stats(db: AsyncSession, tenant_id: str) -> dict:
    tid = uuid.UUID(tenant_id)
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)

    targets_count = (await db.execute(
        select(func.count()).select_from(OJSTarget)
        .where(OJSTarget.tenant_id == tid)
    )).scalar()

    scans_result = await db.execute(
        select(ScanJob).where(
            ScanJob.tenant_id == tid,
            ScanJob.created_at >= month_ago,
        )
    )
    scans = scans_result.scalars().all()
    completed = [s for s in scans if s.status == "completed"]

    avg_score = (
        sum(s.overall_score for s in completed if s.overall_score) / len(completed)
        if completed else None
    )

    critical_count = sum(s.critical_count for s in completed)
    high_count = sum(s.high_count for s in completed)

    return {
        "targets": {"total": targets_count},
        "scans": {
            "last_30_days": len(scans),
            "completed": len(completed),
            "failed": sum(1 for s in scans if s.status == "failed"),
        },
        "security_posture": {
            "average_score": round(avg_score, 1) if avg_score else None,
        },
        "findings_summary": {
            "critical": critical_count,
            "high": high_count,
        },
    }


@router.get("/stats")
async def dashboard_stats(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = current["tenant_id"]
    cache_key = f"dashboard_stats:{tenant_id}"
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    cached = await r.get(cache_key)
    if cached:
        await r.aclose()
        return json.loads(cached)

    stats = await _build_stats(db, tenant_id)
    await r.setex(cache_key, 60, json.dumps(stats))
    await r.aclose()
    return stats
