from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from datetime import datetime, timezone
from app.database import AsyncSessionLocal
from app.models import OJSTarget, ScanJob
from app.celery_app import celery_app

router = APIRouter(prefix="/plugin/v1", tags=["plugin"])


@router.post("/callback")
async def plugin_callback(request: Request):
    target: OJSTarget = request.state.plugin_target
    body: bytes = request.state.plugin_body

    import json
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    event = payload.get("event")

    async with AsyncSessionLocal() as session:
        # Re-fetch target in this session
        result = await session.execute(
            select(OJSTarget).where(OJSTarget.id == target.id)
        )
        t = result.scalar_one()

        if event == "heartbeat":
            t.plugin_last_seen = datetime.now(timezone.utc)
            await session.commit()
            return {"status": "ok"}

        if event == "audit_data":
            job_id = payload.get("job_id")
            if not job_id:
                raise HTTPException(400, "job_id required")
            result = await session.execute(
                select(ScanJob).where(ScanJob.id == job_id, ScanJob.status == "running")
            )
            job = result.scalar_one_or_none()
            if not job:
                raise HTTPException(404, "Scan job tidak ditemukan atau tidak dalam status running")

            celery_app.send_task(
                "app.workers.internal_bot.process_plugin_data_task",
                args=[str(job.id), payload.get("data", {})],
                queue="internal_scan",
            )
            return {"status": "received", "queued": True}

    raise HTTPException(400, "Event tidak dikenal")
