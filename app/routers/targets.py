import uuid
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import OJSTarget
from app.schemas.targets import (
    CreateTargetRequest, TargetResponse, VerifyResponse, PluginGuideResponse,
)
from app.services.targets import (
    compute_plugin_status, create_target, verify_domain_file,
    verify_domain_dns, regenerate_api_key,
)
from app.services.crypto import decrypt_api_key
from app.services.auth import get_current_user

router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


def _to_response(t: OJSTarget) -> TargetResponse:
    return TargetResponse(
        id=str(t.id), name=t.name, url=t.url,
        is_verified=t.is_verified,
        plugin_connected=compute_plugin_status(t),
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
    if await verify_domain_file(target.url, token):
        target.is_verified = True
        await db.commit()
        return VerifyResponse(verified=True, method="file")
    domain = urlparse(target.url).hostname
    if await verify_domain_dns(domain, token):
        target.is_verified = True
        await db.commit()
        return VerifyResponse(verified=True, method="dns")
    return VerifyResponse(verified=False)


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
