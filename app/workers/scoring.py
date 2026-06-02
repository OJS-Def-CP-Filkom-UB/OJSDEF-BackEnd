import asyncio
import json
from datetime import datetime, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import make_worker_session
from app.models import ScanJob, ScanFinding
from app.services.report import generate_pdf_report
from app.workers.utils import write_progress
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()


def _compute_score(crit: int, high: int, med: int, low: int) -> float:
    return max(0.0, 100.0 - (crit * 30 + high * 15 + med * 5 + low * 1))


def _risk_level(score: float) -> str:
    if score <= 25:
        return "critical"
    if score <= 50:
        return "high"
    if score <= 75:
        return "medium"
    return "low"


async def _run_scoring(job_id: str):
    await write_progress(job_id, "scoring", 1, 3, "Menghitung skor risiko CVSS...", "TASK")

    async with make_worker_session() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        findings = (await session.execute(
            select(ScanFinding).where(
                ScanFinding.job_id == job_id,
                ScanFinding.is_false_positive == False,
            )
        )).scalars().all()

        counts = {s: sum(1 for f in findings if f.severity == s)
                  for s in ("critical", "high", "medium", "low")}
        score = _compute_score(counts["critical"], counts["high"], counts["medium"], counts["low"])

        job.overall_score = score
        job.risk_level = _risk_level(score)
        job.critical_count = counts["critical"]
        job.high_count = counts["high"]
        job.medium_count = counts["medium"]
        job.low_count = counts["low"]
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)

        sorted_findings = sorted(findings, key=lambda f: f.cvss_score, reverse=True)

        await write_progress(job_id, "scoring", 2, 3, "Membuat laporan PDF...", "TASK")
        await generate_pdf_report(session, job, sorted_findings)
        await session.commit()

    await write_progress(job_id, "scoring", 3, 3, "Scan selesai", "DONE")

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    await r.delete(f"dashboard_stats:{str(job.tenant_id)}")
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["scoring_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()

    if counts["critical"] > 0:
        crit_ids = [str(f.id) for f in findings if f.severity == "critical"]
        celery_app.send_task(
            "app.workers.notify.send_critical_alert",
            args=[job_id, crit_ids], queue="notifications",
        )


@celery_app.task(name="app.workers.scoring.scoring_task",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def scoring_task(self, job_id: str):
    asyncio.run(_run_scoring(job_id))
