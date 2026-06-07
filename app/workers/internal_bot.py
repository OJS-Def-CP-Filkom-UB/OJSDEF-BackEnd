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


async def _load_target_and_job(job_id: str, target_id: str):
    """Return (target, job_exists). target None jika tidak ditemukan."""
    async with make_worker_session() as session:
        target = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )).scalar_one_or_none()
        job = (await session.execute(
            select(ScanJob).where(ScanJob.id == job_id)
        )).scalar_one_or_none()
    return target, (job is not None)


async def _set_connection_mode(target_id: str, mode: str) -> None:
    async with make_worker_session() as session:
        t = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )).scalar_one_or_none()
        if t:
            t.connection_mode = mode
            await session.commit()


async def _queue_heartbeat_job(target_id: str, job_id: str) -> None:
    async with make_worker_session() as session:
        t = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )).scalar_one_or_none()
        if t:
            t.pending_scan_job_id = uuid.UUID(job_id)
            await session.commit()


async def _setup_internal_scan(job_id: str, target_id: str) -> None:
    """Pre-flight probe → direct trigger, atau fail-fast dengan diagnosa.

    force_heartbeat=True melewati probe dan masuk antrian heartbeat (opt-in firewall).
    """
    target, job_exists = await _load_target_and_job(job_id, target_id)
    if not target or not job_exists:
        return

    api_key = (
        decrypt_api_key(target.plugin_api_key_encrypted)
        if target.plugin_api_key_encrypted else None
    )

    await write_progress(
        job_id, "internal_audit", 1, 2,
        "Mengirim permintaan audit ke plugin OJS...", "TASK",
    )

    # Opt-in heartbeat (OJS di balik firewall) — perilaku lama, eksplisit
    if getattr(target, "force_heartbeat", False):
        await write_progress(
            job_id, "internal_audit", 2, 2,
            "Mode heartbeat — menunggu jadwal berikutnya...", "INFO",
        )
        await _queue_heartbeat_job(target_id, job_id)
        return

    if not api_key or not target.probe_endpoint:
        await _fail_job(
            job_id, "PLUGIN_UNREACHABLE",
            "Plugin belum mengirim endpoint atau API key belum diset. "
            "Pastikan plugin OJSDef aktif dan sudah mengirim heartbeat minimal sekali.",
        )
        return

    result, code, detail = await _probe_for_scan(target.probe_endpoint, api_key)
    if result != "DIRECT":
        await _fail_job(job_id, code, detail)
        return

    if not target.trigger_endpoint:
        await _fail_job(job_id, "TRIGGER_REJECTED", "trigger_endpoint kosong di target")
        return

    triggered = await _trigger_plugin_direct(target.trigger_endpoint, api_key, job_id)
    if triggered:
        await _set_connection_mode(target_id, "direct")
        await write_progress(
            job_id, "internal_audit", 2, 2,
            "Plugin merespons, menunggu callback...", "INFO",
        )
    else:
        await _fail_job(
            job_id, "TRIGGER_REJECTED",
            "Plugin tidak membalas HTTP 202 pada /trigger",
        )


async def _run_internal_scan(job_id: str, data: dict) -> None:
    """Process plugin-provided scan data and persist findings."""
    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 1, 7, "Plugin callback diterima, memproses data audit...", "INFO")

    results = data.get("results", {})
    module_errors: dict[str, str] = {}
    all_findings: list = []

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 2, 7, "Menganalisis konfigurasi OJS...", "TASK")
    try:
        all_findings += scan_config(results.get("config", {}))
    except Exception as e:
        module_errors["config"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 3, 7, "Memeriksa plugin yang terpasang...", "TASK")
    try:
        all_findings += scan_plugins(results.get("plugins", {}))
    except Exception as e:
        module_errors["plugins"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 4, 7, "Mengaudit RBAC dan pengguna...", "TASK")
    try:
        all_findings += scan_rbac(results.get("rbac", {}))
    except Exception as e:
        module_errors["rbac"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 5, 7, "Memeriksa integritas file...", "TASK")
    try:
        fi_data = results.get("file_integrity", {})
        if fi_data.get("status") == "skipped":
            module_errors["file_integrity"] = fi_data.get("reason", "checksums_unavailable")
        else:
            all_findings += scan_file_integrity(fi_data)
    except Exception as e:
        module_errors["file_integrity"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "internal_audit", 6, 7, "Mendeteksi konten mencurigakan...", "TASK")
    try:
        all_findings += scan_content(results.get("content", {}))
    except Exception as e:
        module_errors["content"] = str(e)[:100]

    ojs_version = results.get("fingerprint", {}).get("ojs_version")

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
                references=json.dumps(f.references) if f.references else None,
                remediation_steps=json.dumps(f.remediation_steps) if f.remediation_steps else None,
            ))
        job.module_errors = json.dumps(module_errors) if module_errors else None

        if ojs_version and isinstance(ojs_version, str):
            target = await session.get(OJSTarget, job.target_id)
            if target and target.ojs_version != ojs_version:
                target.ojs_version = ojs_version

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
