import asyncio
import hmac
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.celery_app import celery_app
from app.database import make_worker_session
from app.models import OJSTarget, ScanJob, ScanFinding
from app.scanners.internal.config_scanner import scan_config
from app.scanners.internal.plugin_auditor import scan_plugins
from app.scanners.internal.rbac_auditor import scan_rbac
from app.scanners.internal.file_integrity import scan_file_integrity
from app.scanners.internal.content_detector import scan_content
from app.scanners.internal.db_security import scan_db_security
from app.services.crypto import decrypt_api_key
from app.workers.utils import _try_trigger_scoring
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()

DEFAULT_MODULES = ["fingerprint", "config", "plugins", "rbac", "file_integrity", "content"]


def _sign_for_plugin(api_key: str, body: bytes) -> dict:
    """Mirrors PHP HmacSigner.sign(): timestamp + '.' + body."""
    ts = int(time.time())
    message = str(ts).encode() + b"." + body
    sig = "sha256=" + hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-OJSDef-Signature": sig,
        "X-OJSDef-Timestamp": str(ts),
    }


async def _trigger_plugin_direct(trigger_endpoint: str, api_key: str, job_id: str) -> bool:
    """POST to plugin's /trigger endpoint (Direct Mode). Returns True on HTTP 202."""
    body = json.dumps({"job_id": job_id, "scan_modules": DEFAULT_MODULES}).encode()
    headers = _sign_for_plugin(api_key, body)
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
            resp = await client.post(trigger_endpoint, content=body, headers=headers)
        return resp.status_code == 202
    except Exception:
        return False


async def _setup_internal_scan(job_id: str, target_id: str) -> None:
    """Set job to 'running' and trigger the plugin via Direct or Heartbeat mode."""
    async with make_worker_session() as session:
        target = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )).scalar_one_or_none()
        if not target:
            return

        job = (await session.execute(
            select(ScanJob).where(ScanJob.id == job_id)
        )).scalar_one_or_none()
        if not job:
            return

        api_key = (
            decrypt_api_key(target.plugin_api_key_encrypted)
            if target.plugin_api_key_encrypted
            else None
        )
        connection_mode = target.connection_mode or "unknown"
        trigger_ep = target.trigger_endpoint

    # Direct Mode: POST to plugin's trigger endpoint
    if connection_mode == "direct" and trigger_ep and api_key:
        success = await _trigger_plugin_direct(trigger_ep, api_key, job_id)
        if success:
            return
        # Direct Mode failed — fall through to heartbeat mode

    # Heartbeat Mode (or fallback): store pending job; plugin picks up on next heartbeat
    async with make_worker_session() as session:
        result = await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )
        t = result.scalar_one_or_none()
        if t:
            t.pending_scan_job_id = uuid.UUID(job_id)
            if connection_mode == "direct":
                t.connection_mode = "heartbeat"
            await session.commit()


async def _run_internal_scan(job_id: str, data: dict) -> None:
    """Process plugin-provided scan data and persist findings."""
    all_findings = (
        scan_config(data.get("config", {}))
        + scan_plugins(data.get("plugins", []))
        + scan_rbac(data.get("users", []))
        + scan_file_integrity(data.get("file_integrity", {}))
        + scan_content(data.get("articles", []))
        + scan_db_security(data.get("db_config", {}))
    )
    async with make_worker_session() as session:
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
    await _try_trigger_scoring(job_id)


@celery_app.task(
    name="app.workers.internal_bot.internal_scan_task",
    bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60,
)
def internal_scan_task(self, job_id: str, target_id: str):
    """Trigger the OJSDef plugin to run an internal scan.
    Direct Mode: POST to plugin's /trigger endpoint immediately.
    Heartbeat Mode: store pending job; plugin picks up on next heartbeat (~5 min).
    """
    asyncio.run(_setup_internal_scan(job_id, target_id))


@celery_app.task(
    name="app.workers.internal_bot.process_plugin_data_task",
    bind=True, max_retries=3,
    autoretry_for=(Exception,), default_retry_delay=60,
)
def process_plugin_data_task(self, job_id: str, data: dict):
    """Process scan data received from plugin callback and persist findings."""
    asyncio.run(_run_internal_scan(job_id, data))
