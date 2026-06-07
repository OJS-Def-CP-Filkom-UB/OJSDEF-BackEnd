import asyncio
import uuid
import json
from sqlalchemy import select
from urllib.parse import urlparse
from app.celery_app import celery_app
from app.database import make_worker_session
from app.models import OJSTarget, ScanJob, ScanFinding
from app.scanners.external.fingerprinter import scan_fingerprint
from app.scanners.external.ssl_analyzer import scan_ssl, scan_http_redirect
from app.scanners.external.cookie_analyzer import scan_cookies
from app.scanners.external.endpoint_checker import scan_ojs_endpoints
from app.scanners.external.header_checker import scan_headers
from app.scanners.external.vuln_prober import scan_vulnerabilities
from app.scanners.external.open_dir_detector import scan_open_dirs
from app.scanners.external.cve_matcher import scan_cve
from app.workers.utils import _try_trigger_scoring, write_progress, _check_cancelled
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()


async def _run_external_scan(job_id: str, target_url: str):
    hostname = urlparse(target_url).hostname
    module_errors: dict[str, str] = {}
    all_findings: list = []
    ojs_version = None

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 1, 9, "Mendeteksi versi OJS dan fingerprint...", "TASK")
    try:
        ojs_version, fp = await scan_fingerprint(target_url)
        all_findings += fp
    except Exception as e:
        module_errors["fingerprint_ext"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 2, 9, "Memeriksa SSL/TLS dan redirect HTTP ke HTTPS...", "TASK")
    try:
        ssl_findings = scan_ssl(hostname) if hostname else []
        redirect_findings = await scan_http_redirect(hostname) if hostname else []
        all_findings += ssl_findings + redirect_findings
    except Exception as e:
        module_errors["ssl"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 3, 9, "Menganalisis HTTP security headers...", "TASK")
    try:
        all_findings += await scan_headers(target_url)
    except Exception as e:
        module_errors["headers"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 4, 9, "Menguji kerentanan yang diketahui...", "TASK")
    try:
        all_findings += await scan_vulnerabilities(target_url)
    except Exception as e:
        module_errors["vulnerabilities"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 5, 9, "Memeriksa direktori dan file sensitif...", "TASK")
    try:
        all_findings += await scan_open_dirs(target_url)
    except Exception as e:
        module_errors["open_dirs"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 6, 9, "Mencocokkan CVE dari NVD...", "TASK")
    try:
        all_findings += await scan_cve(ojs_version)
    except Exception as e:
        module_errors["cve"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 7, 9, "Memeriksa keamanan cookie sesi...", "TASK")
    try:
        all_findings += await scan_cookies(target_url)
    except Exception as e:
        module_errors["cookies"] = str(e)[:100]

    if await _check_cancelled(job_id): return
    await write_progress(job_id, "external_scan", 8, 9, "Memeriksa aksesibilitas endpoint OJS...", "TASK")
    try:
        all_findings += await scan_ojs_endpoints(target_url)
    except Exception as e:
        module_errors["endpoints"] = str(e)[:100]

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

    await write_progress(
        job_id, "external_scan", 9, 9,
        f"Pemindaian eksternal selesai — {len(all_findings)} temuan", "DONE",
    )
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    raw = await r.get(f"scan_progress:{job_id}")
    progress = json.loads(raw) if raw else {}
    progress["external_done"] = True
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps(progress))
    await r.aclose()
    if await _check_cancelled(job_id): return
    await _try_trigger_scoring(job_id)


@celery_app.task(name="app.workers.external_bot.external_scan_task",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def external_scan_task(self, job_id: str, target_url: str):
    asyncio.run(_run_external_scan(job_id, target_url))
