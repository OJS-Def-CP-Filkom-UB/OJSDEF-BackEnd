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
from app.services.crypto import decrypt_api_key
from app.workers.utils import _try_trigger_scoring, write_progress, _check_cancelled
import redis.asyncio as aioredis
from app.config import get_settings
from app.workers.diagnostics import DIAGNOSTIC_CODES  # noqa: F401

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


async def _probe_for_scan(probe_endpoint: str, api_key: str) -> tuple[str, str | None, str | None]:
    """Probe sinkron untuk menentukan reachability saat scan dijalankan.

    Returns (result, diagnostic_code, detail):
      - ("DIRECT", None, None)         plugin reachable & challenge cocok
      - ("FAIL", <code>, <detail>)     gagal, dengan kode diagnosa
    """
    challenge = uuid.uuid4().hex
    body = json.dumps({"challenge": challenge}).encode()
    headers = _sign_for_plugin(api_key, body)
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            resp = await client.post(probe_endpoint, content=body, headers=headers)
    except Exception as exc:
        return ("FAIL", "PLUGIN_UNREACHABLE", f"{type(exc).__name__}: {exc}")

    if resp.status_code == 401:
        return ("FAIL", "HMAC_MISMATCH", "HTTP 401 di /probe — API key tidak cocok")
    if resp.status_code >= 500:
        return ("FAIL", "PROBE_HTTP_500", f"HTTP {resp.status_code} di /probe")
    if resp.status_code != 200:
        return ("FAIL", "PLUGIN_UNREACHABLE", f"HTTP {resp.status_code} di /probe")
    try:
        echoed = resp.json().get("challenge", "")
    except Exception:
        echoed = ""
    if echoed != challenge:
        return ("FAIL", "CHALLENGE_MISMATCH", "Challenge tidak di-echo dengan benar")
    return ("DIRECT", None, None)


async def _fail_job(job_id: str, code: str, detail: str) -> None:
    """Tandai job failed + simpan diagnosa, lalu tulis WARN ke progress log."""
    async with make_worker_session() as session:
        job = (await session.execute(
            select(ScanJob).where(ScanJob.id == job_id)
        )).scalar_one_or_none()
        if job:
            job.status = "failed"
            job.completed_at = datetime.now(timezone.utc)
            job.diagnostic_code = code
            job.diagnostic_detail = detail
            job.error_message = detail
            await session.commit()
    await write_progress(
        job_id, "internal_audit", 0, 0,
        f"Scan gagal — {code}: {detail}", "WARN",
    )


async def _setup_internal_scan(job_id: str, target_id: str) -> None:
    """Trigger the plugin via Direct or Heartbeat mode."""
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

    await write_progress(job_id, "internal_audit", 1, 2, "Mengirim permintaan audit ke plugin OJS...", "TASK")

    if connection_mode == "direct" and trigger_ep and api_key:
        success = await _trigger_plugin_direct(trigger_ep, api_key, job_id)
        if success:
            await write_progress(job_id, "internal_audit", 2, 2, "Plugin merespons, menunggu callback...", "INFO")
            return

    await write_progress(job_id, "internal_audit", 2, 2, "Mode heartbeat — menunggu jadwal berikutnya...", "INFO")
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
    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 1, 7, "Plugin callback diterima, memproses data audit...", "INFO")

    results = data.get("results", {})

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 2, 7, "Menganalisis konfigurasi OJS...", "TASK")
    config_findings = scan_config(results.get("config", {}))

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 3, 7, "Memeriksa plugin yang terpasang...", "TASK")
    plugin_findings = scan_plugins(results.get("plugins", {}))

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 4, 7, "Mengaudit RBAC dan pengguna...", "TASK")
    rbac_findings = scan_rbac(results.get("rbac", {}))

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 5, 7, "Memeriksa integritas file...", "TASK")
    file_findings = scan_file_integrity(results.get("file_integrity", {}))

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 6, 7, "Mendeteksi konten mencurigakan...", "TASK")
    content_findings = scan_content(results.get("content", {}))

    all_findings = (
        config_findings + plugin_findings + rbac_findings
        + file_findings + content_findings
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

    if await _check_cancelled(job_id): return
    await write_progress(
        job_id, "internal_audit", 7, 7,
        f"Pemindaian internal selesai — {len(all_findings)} temuan", "DONE",
    )

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
    asyncio.run(_setup_internal_scan(job_id, target_id))


@celery_app.task(
    name="app.workers.internal_bot.process_plugin_data_task",
    bind=True, max_retries=3,
    autoretry_for=(Exception,), default_retry_delay=60,
)
def process_plugin_data_task(self, job_id: str, data: dict):
    asyncio.run(_run_internal_scan(job_id, data))
