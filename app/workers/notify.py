import asyncio
import uuid
import os
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
import httpx
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import ScanJob, ScanFinding, OJSTarget, User, Notification
from app.config import get_settings

settings = get_settings()
_jinja = Environment(loader=FileSystemLoader(
    os.path.join(os.path.dirname(__file__), "..", "templates")
))


async def _email(to: str, subject: str, html: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, settings.smtp_from, to
    msg.attach(MIMEText(html, "html"))
    try:
        await aiosmtplib.send(msg, hostname=settings.smtp_host, port=settings.smtp_port,
                               username=settings.smtp_user, password=settings.smtp_pass,
                               start_tls=True)
        return True
    except Exception:
        return False


async def _telegram(chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json={"chat_id": chat_id, "text": text[:4096]})
            return r.status_code == 200
    except Exception:
        return False


async def _run_critical_alert(job_id: str, finding_ids: list[str]):
    async with AsyncSessionLocal() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one()
        target = (await session.execute(select(OJSTarget).where(OJSTarget.id == job.target_id))).scalar_one()
        findings = (await session.execute(
            select(ScanFinding).where(
                ScanFinding.id.in_(finding_ids),
                ScanFinding.tenant_id == job.tenant_id,
            )
        )).scalars().all()
        users = [u for u in (await session.execute(
            select(User).where(User.tenant_id == job.tenant_id, User.is_active == True)
        )).scalars() if u.notif_email or u.notif_telegram]

        subject = f"[OJSDef] Ancaman Kritis Terdeteksi — {target.name}"
        html_body = _jinja.get_template("email_critical.html").render(
            target_name=target.name, target_url=target.url,
            overall_score=job.overall_score, risk_level=job.risk_level,
            findings=findings,
            dashboard_url=settings.allowed_origins_list[0] + "/dashboard",
        )
        tg_text = (
            f"Ancaman Kritis — {target.name}\n"
            f"Skor: {job.overall_score}/100 ({job.risk_level})\n"
            + "\n".join(f"- {f.title}" for f in findings[:5])
        )

        for user in users:
            if user.notif_email:
                sent = await _email(user.email, subject, html_body)
                session.add(Notification(
                    id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                    user_id=user.id, channel="email", notif_type="critical_alert",
                    is_sent=sent, error_log=None if sent else "SMTP failed",
                ))
            if user.notif_telegram and user.telegram_chat_id:
                sent = await _telegram(user.telegram_chat_id, tg_text)
                session.add(Notification(
                    id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                    user_id=user.id, channel="telegram", notif_type="critical_alert",
                    is_sent=sent, error_log=None if sent else "Telegram API failed",
                ))
        await session.commit()


@celery_app.task(name="app.workers.notify.send_critical_alert",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def send_critical_alert(self, job_id: str, finding_ids: list[str]):
    asyncio.run(_run_critical_alert(job_id, finding_ids))
