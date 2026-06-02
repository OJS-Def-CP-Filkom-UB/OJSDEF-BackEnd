import json

import redis.asyncio as aioredis

from app.celery_app import celery_app
from app.config import get_settings

settings = get_settings()


async def _try_trigger_scoring(job_id: str) -> None:
    """Trigger scoring_task tepat sekali ketika semua komponen scan selesai.

    Membaca scan_type dari Redis progress untuk menentukan kondisi 'ready'.
    Menggunakan Redis SET NX sebagai distributed lock agar scoring tidak
    dipanggil dua kali meskipun external dan internal selesai hampir bersamaan.
    """
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
