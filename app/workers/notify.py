import asyncio
import uuid
import os
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select, or_
import httpx
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.celery_app import celery_app
from app.database import make_worker_session
from app.models import ScanJob, ScanFinding, OJSTarget, User, Notification
from app.config import get_settings

settings = get_settings()
_jinja = Environment(loader=FileSystemLoader(
    os.path.join(os.path.dirname(__file__), "..", "templates")
))

_SCAN_TYPE_LABELS = {
    "internal": "Audit Internal",
    "external": "Scan Eksternal",
    "full": "Audit Penuh",
}
_RISK_LABELS = {
    "critical": "KRITIS",
    "high": "BERBAHAYA",
    "medium": "PERHATIAN",
    "low": "AMAN",
}


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


# ── Welcome ────────────────────────────────────────────────────────────────────

async def _run_send_welcome(user_id: str):
    async with make_worker_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.telegram_chat_id:
            return

        text = (
            "🎉 Selamat datang di OJSDef!\n\n"
            "Akun Anda telah berhasil terhubung ke Telegram.\n\n"
            f"📧 Email: {user.email}\n"
            "🔑 Password sementara dikirimkan oleh admin Anda.\n\n"
            "⚠️ Wajib mengganti password saat pertama login!\n\n"
            f"🌐 Login di: {settings.frontend_base_url}/login\n\n"
            "Bot ini akan mengirimkan notifikasi keamanan OJS Anda\n"
            "secara otomatis. Tidak perlu membalas pesan ini."
        )
        sent = await _telegram(user.telegram_chat_id, text)
        session.add(Notification(
            id=uuid.uuid4(), tenant_id=user.tenant_id, job_id=None,
            user_id=user.id, channel="telegram", notif_type="welcome",
            is_sent=sent, error_log=None if sent else "Telegram API failed",
        ))
        await session.commit()


@celery_app.task(name="app.workers.notify.send_welcome",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def send_welcome(self, user_id: str):
    asyncio.run(_run_send_welcome(user_id))


# ── Scan Completed ─────────────────────────────────────────────────────────────

async def _run_send_scan_completed(job_id: str):
    async with make_worker_session() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one_or_none()
        if not job:
            return
        if job.status != "completed":
            return

        target_result = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == job.target_id)
        )).scalar_one_or_none()
        if not target_result:
            return

        users = (await session.execute(
            select(User).where(
                User.tenant_id == job.tenant_id,
                User.is_active == True,
                User.notif_telegram == True,
                User.telegram_chat_id.isnot(None),
            )
        )).scalars().all()

        if not users:
            return

        scan_type_label = _SCAN_TYPE_LABELS.get(job.scan_type, job.scan_type)
        risk_label = _RISK_LABELS.get(job.risk_level or "", job.risk_level or "N/A")
        wib = timezone(timedelta(hours=7))
        created_wib = job.created_at.astimezone(wib).strftime("%d/%m/%Y %H:%M")

        text = (
            f"✅ Scan Selesai — {target_result.name}\n\n"
            f"Jenis Scan : {scan_type_label}\n"
            f"Skor Risiko: {job.overall_score}/100 — {risk_label}\n"
            f"Waktu Scan : {created_wib} WIB\n\n"
            "Ringkasan Temuan:\n"
            f"🔴 Kritis   : {job.critical_count}\n"
            f"🟠 Berbahaya: {job.high_count}\n"
            f"🟡 Perhatian: {job.medium_count}\n"
            f"🟢 Aman     : {job.low_count}\n\n"
            f"🔗 Lihat Laporan: {settings.frontend_base_url}/vulnerability-report"
        )

        for user in users:
            sent = await _telegram(user.telegram_chat_id, text)
            session.add(Notification(
                id=uuid.uuid4(), tenant_id=job.tenant_id, job_id=job.id,
                user_id=user.id, channel="telegram", notif_type="scan_completed",
                is_sent=sent, error_log=None if sent else "Telegram API failed",
            ))
        await session.commit()


@celery_app.task(name="app.workers.notify.send_scan_completed",
                 bind=True, max_retries=3, autoretry_for=(Exception,), default_retry_delay=60)
def send_scan_completed(self, job_id: str):
    asyncio.run(_run_send_scan_completed(job_id))


# ── Critical Alert ─────────────────────────────────────────────────────────────

async def _run_critical_alert(job_id: str, finding_ids: list[str]):
    async with make_worker_session() as session:
        job = (await session.execute(select(ScanJob).where(ScanJob.id == job_id))).scalar_one_or_none()
        if not job:
            return
        if job.status != "completed":
            return
        target_result = (await session.execute(
            select(OJSTarget).where(OJSTarget.id == job.target_id)
        )).scalar_one_or_none()
        if not target_result:
            return
        findings = (await session.execute(
            select(ScanFinding).where(
                ScanFinding.id.in_(finding_ids),
                ScanFinding.tenant_id == job.tenant_id,
            )
        )).scalars().all()
        users = (await session.execute(
            select(User).where(
                User.tenant_id == job.tenant_id,
                User.is_active == True,
                or_(
                    User.notif_email == True,
                    User.notif_telegram == True,
                ),
            )
        )).scalars().all()

        if not users:
            return

        subject = f"[OJSDef] Ancaman Kritis Terdeteksi — {target_result.name}"
        html_body = _jinja.get_template("email_critical.html").render(
            target_name=target_result.name, target_url=target_result.url,
            overall_score=job.overall_score, risk_level=job.risk_level,
            findings=findings,
            dashboard_url=settings.allowed_origins_list[0] + "/dashboard",
        )

        findings_list = "\n".join(f"• {f.title}" for f in findings[:5])
        count = len(findings)

        tg_text = (
            "🚨 ANCAMAN KRITIS TERDETEKSI\n\n"
            f"Target: {target_result.name}\n"
            f"URL: {target_result.url}\n"
            f"Skor Risiko: {job.overall_score}/100 — KRITIS\n\n"
            f"Temuan Kritis ({count} temuan):\n"
            f"{findings_list}\n\n"
            "⏱ SLA Perbaikan: 24 jam\n"
            f"🔗 Lihat Detail: {settings.frontend_base_url}/vulnerability-report\n\n"
            "Segera tindaklanjuti sebelum sistem Anda dieksploitasi."
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
