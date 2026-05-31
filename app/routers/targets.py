import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import OJSTarget
from app.schemas.targets import (
    CreateTargetRequest, TargetResponse, VerifyResponse,
    PluginGuideResponse, FileMethodInfo, DnsMethodInfo,
)
from app.services.targets import (
    compute_plugin_status, create_target, verify_domain_file,
    verify_domain_dns, regenerate_api_key,
)
from app.services.crypto import decrypt_api_key
from app.services.auth import get_current_user
from app.core.audit import create_audit_log


def _compute_plugin_status_str(t: OJSTarget) -> str:
    if not t.plugin_last_seen:
        return "never_connected"
    threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
    last_seen = t.plugin_last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if last_seen >= threshold:
        return "connected"
    if t.connection_mode == "error":
        return "error"
    return "disconnected"


router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


def _to_response(t: OJSTarget) -> TargetResponse:
    status_str = _compute_plugin_status_str(t)
    return TargetResponse(
        id=str(t.id),
        name=t.name,
        url=t.url,
        is_verified=t.is_verified,
        plugin_connected=(status_str == "connected"),
        plugin_status=status_str,
        connection_mode=t.connection_mode,
        last_heartbeat=t.plugin_last_seen,
        verification_token=t.verification_token,
        ojs_version=t.ojs_version,
        created_at=t.created_at,
    )


@router.get("", response_model=list[TargetResponse])
async def list_targets(
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget))
    return [_to_response(t) for t in result.scalars()]


@router.post("", response_model=TargetResponse, status_code=201)
async def add_target(
    body: CreateTargetRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await create_target(db, uuid.UUID(current["tenant_id"]), body.name, body.url)
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="target.created",
        resource_type="target", resource_id=str(target.id),
        details={"name": target.name, "url": target.url},
    )
    return _to_response(target)


@router.get("/{target_id}", response_model=TargetResponse)
async def get_target(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    return _to_response(target)


@router.delete("/{target_id}", status_code=204)
async def delete_target(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    await db.delete(target)
    await db.commit()


@router.post("/{target_id}/verify", response_model=VerifyResponse)
async def verify_target(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")

    token = target.verification_token
    domain = urlparse(target.url).hostname or target.url

    file_info = FileMethodInfo(
        filename=f"ojsdef-verify-{token}.txt",
        content=f"ojsdef-verification={token}",
        path=f"/.well-known/ojsdef-verify-{token}.txt",
    )
    dns_info = DnsMethodInfo(
        record_type="TXT",
        record_name=f"_ojsdef-verify.{domain}",
        record_value=f"ojsdef-verification={token}",
    )

    if await verify_domain_file(target.url, token):
        target.is_verified = True
        await db.commit()
        await create_audit_log(
            db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
            tenant_id=current.get("tenant_id"), action="target.verified",
            resource_type="target", resource_id=str(target_id), details={"method": "file"},
        )
        return VerifyResponse(
            verified=True, method="file", verification_token=token,
            file_method=file_info, dns_method=dns_info,
        )

    if await verify_domain_dns(domain, token):
        target.is_verified = True
        await db.commit()
        await create_audit_log(
            db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
            tenant_id=current.get("tenant_id"), action="target.verified",
            resource_type="target", resource_id=str(target_id), details={"method": "dns"},
        )
        return VerifyResponse(
            verified=True, method="dns", verification_token=token,
            file_method=file_info, dns_method=dns_info,
        )

    return VerifyResponse(
        verified=False, method=None, verification_token=token,
        file_method=file_info, dns_method=dns_info,
    )


@router.get("/{target_id}/plugin-guide", response_model=PluginGuideResponse)
async def plugin_guide(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    api_key = decrypt_api_key(target.plugin_api_key_encrypted)
    return PluginGuideResponse(
        target_id=str(target.id),
        api_key=api_key,
        endpoint="/plugin/v1/callback",
        instructions="Install plugin OJSDef di OJS, masukkan API Key dan endpoint di atas.",
    )


@router.post("/{target_id}/regenerate-key")
async def regen_key(
    target_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(OJSTarget).where(OJSTarget.id == target_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    new_key = await regenerate_api_key(db, target)
    return {"api_key": new_key}
