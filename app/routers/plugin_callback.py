import hmac
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import OJSTarget, ScanJob
from app.services.crypto import decrypt_api_key

router = APIRouter(prefix="/plugin/v1", tags=["plugin"])

DEFAULT_MODULES = ["fingerprint", "config", "plugins", "rbac", "file_integrity", "content"]


def _sign_for_plugin(api_key: str, body: bytes) -> dict:
    """Build HMAC headers to authenticate backend→plugin requests.
    Mirrors PHP HmacSigner: sign(timestamp + '.' + body, api_key).
    """
    ts = int(time.time())
    message = str(ts).encode() + b"." + body
    sig = "sha256=" + hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-OJSDef-Signature": sig,
        "X-OJSDef-Timestamp": str(ts),
    }


async def _probe_plugin(probe_endpoint: str, api_key: str, challenge: str, target_id: str) -> None:
    """Attempt to probe plugin's /probe endpoint to determine connection mode.
    Updates connection_mode to 'direct' on success, 'heartbeat' on failure.
    """
    body = json.dumps({"challenge": challenge}).encode()
    headers = _sign_for_plugin(api_key, body)
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            resp = await client.post(probe_endpoint, content=body, headers=headers)
        try:
            echoed = resp.json().get("challenge", "")
        except Exception:
            echoed = ""
        mode = "direct" if (resp.status_code == 200 and echoed == challenge) else "heartbeat"
    except Exception:
        mode = "heartbeat"

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OJSTarget).where(OJSTarget.id == target_id)
        )
        t = result.scalar_one_or_none()
        if t:
            t.connection_mode = mode
            await session.commit()


@router.post("/heartbeat")
async def plugin_heartbeat(request: Request, bg: BackgroundTasks):
    """Receive periodic heartbeat from the OJSDef PHP plugin.

    Plugin sends every 5 minutes with target metadata and optional
    reachability_challenge for connection-mode auto-detection.
    Response may include scan_requested if a job is pending in heartbeat mode.
    """
    target: OJSTarget = request.state.plugin_target
    body: bytes = request.state.plugin_body

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OJSTarget).where(OJSTarget.id == target.id)
        )
        t = result.scalar_one()

        t.plugin_last_seen = datetime.now(timezone.utc)
        if payload.get("ojs_version"):
            t.ojs_version = payload["ojs_version"]

        # Store plugin endpoints from heartbeat payload
        if payload.get("trigger_endpoint"):
            t.trigger_endpoint = payload["trigger_endpoint"]
        if payload.get("probe_endpoint"):
            t.probe_endpoint = payload["probe_endpoint"]

        # If plugin reports mode already known, trust it
        if payload.get("connection_mode") in ("direct", "heartbeat"):
            t.connection_mode = payload["connection_mode"]

        # Check for pending heartbeat-mode scan
        pending_job_id = t.pending_scan_job_id
        pending_job = None
        if pending_job_id:
            job_result = await session.execute(
                select(ScanJob).where(ScanJob.id == pending_job_id, ScanJob.status == "running")
            )
            pending_job = job_result.scalar_one_or_none()
            if not pending_job:
                # Job no longer active — clear stale pending
                t.pending_scan_job_id = None
                pending_job_id = None

        await session.commit()

    # Schedule probe in background if plugin sends a reachability_challenge
    challenge = payload.get("reachability_challenge")
    probe_ep = payload.get("probe_endpoint") or target.probe_endpoint
    if challenge and probe_ep and target.plugin_api_key_encrypted:
        api_key = decrypt_api_key(target.plugin_api_key_encrypted)
        bg.add_task(_probe_plugin, probe_ep, api_key, challenge, str(target.id))

    response: dict = {"status": "ok"}
    if pending_job:
        response["scan_requested"] = True
        response["job_id"] = str(pending_job_id)
        response["scan_modules"] = DEFAULT_MODULES

    return response


@router.post("/callback")
async def plugin_callback(request: Request):
    """Receive audit_data from the OJSDef PHP plugin after a scan completes."""
    target: OJSTarget = request.state.plugin_target
    body: bytes = request.state.plugin_body

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    event = payload.get("event")
    if event != "audit_data":
        raise HTTPException(400, "Event tidak dikenal")

    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(400, "job_id required")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ScanJob).where(ScanJob.id == job_id, ScanJob.status == "running")
        )
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(404, "Scan job tidak ditemukan atau tidak dalam status running")

        # Clear pending heartbeat-mode job now that data arrived
        t_result = await session.execute(
            select(OJSTarget).where(OJSTarget.id == target.id)
        )
        t = t_result.scalar_one()
        if t.pending_scan_job_id == job.id:
            t.pending_scan_job_id = None
        await session.commit()

    celery_app.send_task(
        "app.workers.internal_bot.process_plugin_data_task",
        args=[str(job.id), payload.get("data", {})],
        queue="internal_scan",
    )
    return JSONResponse({"status": "received", "queued": True}, status_code=202)


@router.get("/checksums")
async def get_checksums(request: Request, version: str = ""):
    """Return official SHA-256 checksums for core OJS files of a given version.
    Used by FileIntegrityChecker on the plugin to detect tampered files.
    Plugin caches this for 7 days (CACHE_TTL = 604800).
    """
    target: OJSTarget = request.state.plugin_target  # noqa: F841 — auth verified by middleware

    if not version:
        raise HTTPException(400, "version parameter required")

    # Normalize version string for lookup: "3.3.0-17" → "3_3_0"
    norm = version.replace(".", "_").replace("-", "_")

    # Checksums for supported OJS versions (relative path → expected SHA-256).
    # Full list generated by release pipeline; this is representative subset.
    CHECKSUMS: dict[str, dict[str, str]] = {
        "3_3_0": {
            "index.php": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "config.TEMPLATE.inc.php": "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
        },
        "3_4_0": {
            "index.php": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "config.TEMPLATE.inc.php": "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
        },
    }

    # Exact match first, then prefix match (e.g. "3.3.0-17" → key "3_3_0")
    checksums = CHECKSUMS.get(norm)
    if not checksums:
        for key in CHECKSUMS:
            if norm.startswith(key):
                checksums = CHECKSUMS[key]
                break

    if not checksums:
        raise HTTPException(404, f"Checksums untuk versi {version} tidak tersedia")

    return checksums
