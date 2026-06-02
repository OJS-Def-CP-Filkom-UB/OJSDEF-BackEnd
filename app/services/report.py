import uuid
import io
import os
import logging
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import boto3
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ScanJob, OJSTarget, Report
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
_jinja = Environment(loader=FileSystemLoader(
    os.path.join(os.path.dirname(__file__), "..", "templates")
))
SEVERITY_LABEL = {"critical": "Kritis", "high": "Berbahaya", "medium": "Perhatian", "low": "Aman"}


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


async def generate_pdf_report(session: AsyncSession, job: ScanJob, findings: list) -> Report | None:
    try:
        target = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == job.target_id)
        )).scalar_one()
        html = _jinja.get_template("report.html").render(
            job=job, target=target, findings=findings, severity_label=SEVERITY_LABEL,
        )
        output = io.BytesIO()
        result = pisa.CreatePDF(html, dest=output)
        if result.err:
            raise RuntimeError(f"xhtml2pdf error code {result.err}")
        pdf = output.getvalue()
        path = f"{job.tenant_id}/{job.id}/report.pdf"
        _s3().put_object(
            Bucket=settings.minio_bucket, Key=path,
            Body=pdf, ContentType="application/pdf",
        )
        report = Report(
            id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
            format="pdf", storage_path=path, file_size_bytes=len(pdf),
        )
        session.add(report)
        return report
    except Exception as e:
        logger.warning("PDF generation failed for job %s: %s", job.id, e)
        return None
