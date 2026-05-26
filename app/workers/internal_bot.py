import asyncio
import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import ScanJob, ScanFinding
from app.scanners.internal.config_scanner import scan_config
from app.scanners.internal.plugin_auditor import scan_plugins
from app.scanners.internal.rbac_auditor import scan_rbac
from app.scanners.internal.file_integrity import scan_file_integrity
from app.scanners.internal.content_detector import scan_content
from app.scanners.internal.db_security import scan_db_security
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()


async def _run_internal_scan(job_id: str, data: dict):
    all_findings = (
        scan_config(data.get("config", {}))
        + scan_plugins(data.get("plugins", []))
        + scan_rbac(data.get("users", []))
        + scan_file_integrity(data.get("file_integrity", {}))
        + scan_content(data.get("articles", []))
        + scan_db_security(data.get("db_config", {}))
    )
    async with AsyncSessionLocal() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        for f in all_findings:
            session.add(ScanFinding(
                id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                finding_type=f.finding_type, category=f.category, title=f.title,
                description=f.description, affected_path=f.affected_path,
                evidence=f.evidence, remediation=f.remediation,
                severity=f.severity, cvss_score=f.cvss_score,
                cve_id=f.cve_id, owasp_category=f.owasp_category,
            ))
        await session.commit()
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["internal_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()


@celery_app.task(name="app.workers.internal_bot.internal_scan_task",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def internal_scan_task(self, job_id: str, target_id: str):
    asyncio.run(_run_internal_scan(job_id, {}))


@celery_app.task(
    name="app.workers.internal_bot.process_plugin_data_task",
    bind=True, max_retries=3,
    autoretry_for=(Exception,), default_retry_delay=60,
)
def process_plugin_data_task(self, job_id: str, data: dict):
    asyncio.run(_run_internal_scan(job_id, data))
