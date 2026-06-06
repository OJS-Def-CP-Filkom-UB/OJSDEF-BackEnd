import io
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import boto3
from app.database import get_db
from app.models import Report, ScanFinding, ScanJob
from app.schemas.reports import ReportResponse
from app.services.auth import get_current_user
from app.core.audit import create_audit_log
from app.config import get_settings
from app.routers._tenant_helper import resolve_tenant_filter

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
settings = get_settings()


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


@router.get("", response_model=list[ReportResponse])
async def list_reports(
    tenant_id: str | None = None,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = resolve_tenant_filter(current, tenant_id)
    q = select(Report).order_by(Report.created_at.desc())
    if tid is not None:
        q = q.where(Report.tenant_id == tid)
    result = await db.execute(q)
    return [
        ReportResponse(id=str(r.id), job_id=str(r.job_id), format=r.format,
                       file_size_bytes=r.file_size_bytes, created_at=r.created_at)
        for r in result.scalars()
    ]


@router.get("/{report_id}/pdf")
async def download_pdf(
    report_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Report).where(Report.id == report_id, Report.format == "pdf")
    if current["role"] != "saas_admin":
        q = q.where(Report.tenant_id == uuid.UUID(current["tenant_id"]))
    result = await db.execute(q)
    report = result.scalar_one_or_none()
    if not report or not report.storage_path:
        raise HTTPException(404, "Laporan PDF tidak ditemukan")

    obj = _s3().get_object(Bucket=settings.minio_bucket, Key=report.storage_path)
    pdf_data = obj["Body"].read()

    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="report.exported",
        resource_type="report", resource_id=str(report_id), details={"format": "pdf"},
    )
    filename = f"ojsdef-report-{str(report_id)[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{report_id}/json")
async def download_json(
    report_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Report).where(Report.id == report_id)
    if current["role"] != "saas_admin":
        q = q.where(Report.tenant_id == uuid.UUID(current["tenant_id"]))
    result = await db.execute(q)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Laporan tidak ditemukan")
    job_result = await db.execute(select(ScanJob).where(ScanJob.id == report.job_id))
    job = job_result.scalar_one()
    findings_result = await db.execute(
        select(ScanFinding).where(ScanFinding.job_id == report.job_id)
    )
    findings = findings_result.scalars().all()
    await create_audit_log(
        db, user_id=current.get("sub"), user_email=current.get("email", "unknown"),
        tenant_id=current.get("tenant_id"), action="report.exported",
        resource_type="report", resource_id=str(report_id), details={"format": "json"},
    )
    return {
        "job_id": str(job.id), "scan_type": job.scan_type,
        "status": job.status, "overall_score": job.overall_score, "risk_level": job.risk_level,
        "findings_summary": {
            "total": len(findings),
            "false_positives": sum(1 for f in findings if f.is_false_positive),
        },
        "findings": [
            {
                "title": f.title, "severity": f.severity, "cvss_score": f.cvss_score,
                "description": f.description, "remediation": f.remediation,
                "is_false_positive": f.is_false_positive,
                "false_positive_label": "False Positive" if f.is_false_positive else None,
            }
            for f in findings
        ],
    }
