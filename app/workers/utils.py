import json
import redis.asyncio as aioredis
from app.celery_app import celery_app
from app.config import get_settings

settings = get_settings()


async def _try_trigger_scoring(job_id: str) -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        progress = json.loads(await r.get(f"scan_progress:{job_id}") or "{}")
        scan_type = progress.get("scan_type", "external")
        ext = progress.get("external_done", False)
        itn = progress.get("internal_done", False)
        ready = (
            (scan_type == "external" and ext)
            or (scan_type == "internal" and itn)
            or (scan_type == "full" and ext and itn)
        )
        if ready:
            acquired = await r.set(
                f"scoring_triggered:{job_id}", "1", nx=True, ex=3600
            )
            if acquired:
                celery_app.send_task(
                    "app.workers.scoring.scoring_task",
                    args=[job_id], queue="scoring",
                )
    finally:
        await r.aclose()


async def write_progress(
    job_id: str,
    stage: str,
    step: int,
    total: int,
    message: str,
    log_type: str = "INFO",
) -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await r.get(f"scan_progress:{job_id}")
        data = json.loads(raw) if raw else {}
        data.update({
            "stage": stage,
            "current_step": step,
            "total_steps": total,
            "message": message,
            "log_type": log_type,
        })
        await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(data))
    finally:
        await r.aclose()


async def _check_cancelled(job_id: str) -> bool:
    from app.models import ScanJob
    from app.database import make_worker_session
    from sqlalchemy import select
    async with make_worker_session() as session:
        job = (await session.execute(
            select(ScanJob).where(ScanJob.id == job_id)
        )).scalar_one_or_none()
        return job is not None and job.status == "cancelled"
