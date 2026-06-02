import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis
from app.database import get_db
from app.models import OJSTarget, ScanJob, ScanFinding
from app.schemas.scans import StartScanRequest, ScanResponse, FindingResponse, ScanProgress
from app.services.auth import get_current_user, require_role
from app.core.audit import create_audit_log
from app.celery_app import celery_app
from app.config import get_settings

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])
settings = get_settings()


def _redis():
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _get_progress(job_id: str) -> dict | None:
    r = _redis()
    raw = await r.get(f"scan_progress:{job_id}")
    await r.aclose()
    return json.loads(raw) if raw else None


def _to_response(job: ScanJob, progress: dict | None = None) -> ScanResponse:
    parsed_progress: ScanProgress | None = None
    if progress:
        try:
            parsed_progress = ScanProgress(**progress)
        except Exception:
            parsed_progress = None  # tolak progress yang malformed
    return ScanResponse(
        id=str(job.id), target_id=str(job.target_id),
        scan_type=job.scan_type, status=job.status,
        overall_score=job.overall_score, risk_level=job.risk_level,
        critical_count=job.critical_count, high_count=job.high_count,
        medium_count=job.medium_count, low_count=job.low_count,
        progress=parsed_progress, created_at=job.created_at,
    )


@router.post("", response_model=ScanResponse, status_code=201)
async def start_scan(
    body: StartScanRequest,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OJSTarget).where(OJSTarget.id == body.target_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target tidak ditemukan")
    if not target.is_verified:
        raise HTTPException(400, "Target belum diverifikasi")

    job = ScanJob(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(current["tenant_id"]),
        target_id=target.id,
        scan_type=body.scan_type,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    job_id = str(job.id)
    target_id = str(target.id)
    target_url = target.url

    # Inisialisasi Redis progress sebelum fire tasks
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    await r.setex(f"scan_progress:{job_id}", 3600, json.dumps({
        "scan_type": body.scan_type,
        "external_done": False,
        "internal_done": False,
    }))
    await r.aclose()

    # Fire tasks independen — scoring dikoordinasi oleh _try_trigger_scoring via Redis
    if body.scan_type in ("internal", "full"):
        celery_app.send_task(
            "app.workers.internal_bot.internal_scan_task",
            args=[job_id, target_id], queue="internal_scan",
        )
    if body.scan_type in ("external", "full"):
        celery_app.send_task(
            "app.workers.external_bot.external_scan_task",
            args=[job_id, target_url], queue="external_scan",
        )

    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="scan.started",
        resource_type="scan", resource_id=str(job.id),
        details={"scan_type": body.scan_type, "target_id": str(body.target_id)},
    )
    return _to_response(job)


@router.get("", response_model=list[ScanResponse])
async def list_scans(
    target_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(ScanJob).order_by(ScanJob.created_at.desc()).limit(limit)
    if target_id:
        q = q.where(ScanJob.target_id == target_id)
    if status:
        q = q.where(ScanJob.status == status)
    result = await db.execute(q)
    return [_to_response(j) for j in result.scalars()]


@router.get("/{job_id}", response_model=ScanResponse)
async def get_scan(
    job_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ScanJob).where(ScanJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Scan tidak ditemukan")
    progress = await _get_progress(str(job_id))
    return _to_response(job, progress)


@router.get("/{job_id}/findings", response_model=list[FindingResponse])
async def get_findings(
    job_id: uuid.UUID,
    severity: str | None = None,
    category: str | None = None,
    page: int = 1,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(ScanFinding).where(ScanFinding.job_id == job_id)
    if severity:
        q = q.where(ScanFinding.severity == severity)
    if category:
        q = q.where(ScanFinding.category == category)
    q = q.offset((page - 1) * 20).limit(20)
    result = await db.execute(q)
    findings = result.scalars().all()
    return [
        FindingResponse(
            id=str(f.id), finding_type=f.finding_type, category=f.category,
            title=f.title, description=f.description, affected_path=f.affected_path,
            evidence=f.evidence, remediation=f.remediation, severity=f.severity,
            cvss_score=f.cvss_score, cve_id=f.cve_id, owasp_category=f.owasp_category,
            is_false_positive=f.is_false_positive,
        )
        for f in findings
    ]


@router.patch("/{job_id}/findings/{finding_id}", response_model=FindingResponse)
async def mark_false_positive(
    job_id: uuid.UUID,
    finding_id: uuid.UUID,
    current: dict = Depends(require_role("admin_ojs", "saas_admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScanFinding).where(ScanFinding.id == finding_id, ScanFinding.job_id == job_id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Finding tidak ditemukan")
    f.is_false_positive = not f.is_false_positive
    await db.commit()
    await db.refresh(f)
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="finding.false_positive_toggled",
        resource_type="scan", resource_id=str(finding_id),
        details={"is_false_positive": f.is_false_positive, "job_id": str(job_id)},
    )
    return FindingResponse(
        id=str(f.id), finding_type=f.finding_type, category=f.category,
        title=f.title, description=f.description, affected_path=f.affected_path,
        evidence=f.evidence, remediation=f.remediation, severity=f.severity,
        cvss_score=f.cvss_score, cve_id=f.cve_id, owasp_category=f.owasp_category,
        is_false_positive=f.is_false_positive,
    )
