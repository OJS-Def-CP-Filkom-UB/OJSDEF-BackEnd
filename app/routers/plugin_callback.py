import hmac
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.celery_app import celery_app
from app.database import AsyncSessionLocal, set_tenant_context
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


async def _probe_plugin(
    probe_endpoint: str,
    api_key: str,
    challenge: str,
    target_id: str,
    tenant_id: str,
) -> None:
    """Attempt to probe plugin's /probe endpoint to determine connection mode."""
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
        await set_tenant_context(session, tenant_id, "plugin")
        try:
            result = await session.execute(
                select(OJSTarget).where(OJSTarget.id == target_id)
            )
            t = result.scalar_one_or_none()
            if t:
                t.connection_mode = mode
                await session.commit()
        finally:
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.user_role = ''"))


@router.post("/heartbeat")
async def plugin_heartbeat(request: Request, bg: BackgroundTasks):
    """Receive periodic heartbeat from the OJSDef PHP plugin."""
    target: OJSTarget = request.state.plugin_target
    body: bytes = request.state.plugin_body
    tenant_id = str(target.tenant_id)

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id, "plugin")
        try:
            result = await session.execute(
                select(OJSTarget).where(OJSTarget.id == target.id)
            )
            t = result.scalar_one()

            t.plugin_last_seen = datetime.now(timezone.utc)
            if payload.get("ojs_version"):
                t.ojs_version = payload["ojs_version"]
            if payload.get("trigger_endpoint"):
                t.trigger_endpoint = payload["trigger_endpoint"]
            if payload.get("probe_endpoint"):
                t.probe_endpoint = payload["probe_endpoint"]
            if payload.get("connection_mode") in ("direct", "heartbeat"):
                t.connection_mode = payload["connection_mode"]

            pending_job_id = t.pending_scan_job_id
            pending_job = None
            if pending_job_id:
                job_result = await session.execute(
                    select(ScanJob).where(
                        ScanJob.id == pending_job_id, ScanJob.status == "running"
                    )
                )
                pending_job = job_result.scalar_one_or_none()
                if not pending_job:
                    t.pending_scan_job_id = None
                    pending_job_id = None

            await session.commit()
        finally:
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.user_role = ''"))

    challenge = payload.get("reachability_challenge")
    probe_ep = payload.get("probe_endpoint") or target.probe_endpoint
    if challenge and probe_ep and target.plugin_api_key_encrypted:
        api_key = decrypt_api_key(target.plugin_api_key_encrypted)
        bg.add_task(_probe_plugin, probe_ep, api_key, challenge, str(target.id), tenant_id)

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
    tenant_id = str(target.tenant_id)

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
        await set_tenant_context(session, tenant_id, "plugin")
        try:
            result = await session.execute(
                select(ScanJob).where(ScanJob.id == job_id, ScanJob.status == "running")
            )
            job = result.scalar_one_or_none()
            if not job:
                raise HTTPException(
                    404, "Scan job tidak ditemukan atau tidak dalam status running"
                )

            t_result = await session.execute(
                select(OJSTarget).where(OJSTarget.id == target.id)
            )
            t = t_result.scalar_one()
            if t.pending_scan_job_id == job.id:
                t.pending_scan_job_id = None
            await session.commit()
        finally:
            await session.execute(text("SET app.current_tenant_id = ''"))
            await session.execute(text("SET app.user_role = ''"))

    celery_app.send_task(
        "app.workers.internal_bot.process_plugin_data_task",
        args=[str(job.id), payload.get("data", {})],
        queue="internal_scan",
    )
    return JSONResponse({"status": "received", "queued": True}, status_code=202)


@router.get("/checksums")
async def get_checksums(request: Request, version: str = ""):
    """Return official SHA-256 checksums for core OJS files of a given version."""
    target: OJSTarget = request.state.plugin_target  # noqa: F841 — auth verified by middleware

    if not version:
        raise HTTPException(400, "version parameter required")

    norm = version.replace(".", "_").replace("-", "_")

    CHECKSUMS: dict[str, dict[str, str]] = {
        "3_3_0": {
            "index.php":               "376e1a51db860abaf952b0d4dcce48b7809a58d785648d30d2d38167672b13a2",
            "config.TEMPLATE.inc.php": "b5419455b25b79d303e907c060bbabb6c955fa72465bc04805c238b0226462ce",
        },
        "3_4_0": {
            "index.php":               "95d7797febd50ce9216081f08db80329332632db3383dbf4919748078d40e72f",
            "config.TEMPLATE.inc.php": "8036209f5cd730482367514f3680f503f12ef20625ba9587931445bcab5cb8d0",
        },
    }

    checksums = CHECKSUMS.get(norm)
    if not checksums:
        for key in CHECKSUMS:
            if norm.startswith(key):
                checksums = CHECKSUMS[key]
                break

    if not checksums:
        raise HTTPException(404, f"Checksums untuk versi {version} tidak tersedia")

    return checksums
