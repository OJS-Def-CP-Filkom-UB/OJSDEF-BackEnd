# NOTE: asyncio.run() in these tasks assumes Celery is using the prefork pool
# (default). Do NOT switch to gevent/eventlet pool without replacing asyncio.run()
# with the gevent-compatible async_to_sync() pattern.

import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.scan_job import ScanJob


@celery_app.task(name="app.workers.tasks.cleanup_stale_pending_jobs")
def cleanup_stale_pending_jobs() -> str:
    """Mark queued/running scan jobs > 30 menit tanpa callback sebagai failed."""

    async def _run() -> int:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ScanJob).where(
                    ScanJob.status.in_(["queued", "running"]),
                    ScanJob.created_at < threshold,
                )
            )
            stale = result.scalars().all()
            for job in stale:
                job.status = "failed"
                job.error_message = "Scan timeout: tidak ada respons dalam 30 menit"
            if stale:
                await session.commit()
            return len(stale)

    count = asyncio.run(_run())
    return f"Cleaned up {count} stale pending jobs"
