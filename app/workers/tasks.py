# NOTE: asyncio.run() in these tasks assumes Celery is using the prefork pool
# (default). Do NOT switch to gevent/eventlet pool without replacing asyncio.run()
# with the gevent-compatible async_to_sync() pattern.

import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.scan_job import ScanJob
from app.workers.utils import write_progress

CALLBACK_TIMEOUT_MINUTES = 5
STALE_TIMEOUT_MINUTES = 30


def classify_stale_job(
    status: str,
    scan_type: str,
    started_at: datetime | None,
    created_at: datetime | None,
    now: datetime,
    callback_minutes: int = CALLBACK_TIMEOUT_MINUTES,
    general_minutes: int = STALE_TIMEOUT_MINUTES,
) -> str | None:
    """Klasifikasi job macet. Pure function — mudah diuji.

    - CALLBACK_TIMEOUT: internal/full running > 5 menit (nunggu callback plugin)
    - STALE:            queued/running > 30 menit (jaring umum)
    - None:             tidak macet
    """
    if status not in ("queued", "running"):
        return None
    if (
        status == "running"
        and scan_type in ("internal", "full")
        and started_at is not None
        and started_at < now - timedelta(minutes=callback_minutes)
    ):
        return "CALLBACK_TIMEOUT"
    if created_at is not None and created_at < now - timedelta(minutes=general_minutes):
        return "STALE"
    return None


@celery_app.task(name="app.workers.tasks.cleanup_stale_pending_jobs")
def cleanup_stale_pending_jobs() -> str:
    """Tandai job macet sebagai failed dengan diagnosa yang sesuai."""

    async def _run() -> int:
        now = datetime.now(timezone.utc)
        count = 0
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ScanJob).where(ScanJob.status.in_(["queued", "running"]))
            )
            for job in result.scalars().all():
                verdict = classify_stale_job(
                    status=job.status, scan_type=job.scan_type,
                    started_at=job.started_at, created_at=job.created_at, now=now,
                )
                if verdict is None:
                    continue
                if verdict == "CALLBACK_TIMEOUT":
                    msg = "Scan timeout: plugin menerima permintaan tapi tidak mengirim hasil dalam 5 menit"
                    job.diagnostic_code = "CALLBACK_TIMEOUT"
                else:
                    msg = "Scan timeout: tidak ada respons dalam 30 menit"
                    job.diagnostic_code = job.diagnostic_code or "PLUGIN_UNREACHABLE"
                await write_progress(str(job.id), "scan", 0, 0, msg, "WARN")
                job.status = "failed"
                job.completed_at = now
                job.error_message = msg
                job.diagnostic_detail = job.diagnostic_detail or msg
                count += 1
            if count:
                await session.commit()
            return count

    count = asyncio.run(_run())
    return f"Cleaned up {count} stale pending jobs"
