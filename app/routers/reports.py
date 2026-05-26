import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import boto3
from app.database import get_db
from app.models import Report, ScanFinding, ScanJob
from app.schemas.reports import ReportResponse
from app.services.auth import get_current_user
from app.config import get_settings

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
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Report).order_by(Report.created_at.desc()))
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
    result = await db.execute(select(Report).where(Report.id == report_id, Report.format == "pdf"))
    report = result.scalar_one_or_none()
    if not report or not report.storage_path:
        raise HTTPException(404, "Laporan PDF tidak ditemukan")
    url = _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.minio_bucket, "Key": report.storage_path},
        ExpiresIn=3600,
    )
    return RedirectResponse(url)


@router.get("/{report_id}/json")
async def download_json(
    report_id: uuid.UUID,
    current: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Laporan tidak ditemukan")
    job_result = await db.execute(select(ScanJob).where(ScanJob.id == report.job_id))
    job = job_result.scalar_one()
    findings_result = await db.execute(
        select(ScanFinding).where(ScanFinding.job_id == report.job_id)
    )
    findings = findings_result.scalars().all()
    return {
        "job_id": str(job.id), "scan_type": job.scan_type, "status": job.status,
        "overall_score": job.overall_score, "risk_level": job.risk_level,
        "findings": [
            {"title": f.title, "severity": f.severity, "cvss_score": f.cvss_score,
             "description": f.description, "remediation": f.remediation}
            for f in findings
        ],
    }
