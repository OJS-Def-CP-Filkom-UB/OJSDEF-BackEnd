import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Header
from sqlalchemy import select
import httpx
from app.database import AsyncSessionLocal
from app.models import User
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["telegram"])
settings = get_settings()


async def _bot_reply(chat_id: int, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(url, json={"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.warning("bot_reply failed chat_id=%s: %s", chat_id, e)


@router.post("/telegram/webhook", status_code=200)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if settings.telegram_webhook_secret:
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    body = await request.json()
    message = body.get("message") or body.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id: int | None = message.get("from", {}).get("id")
    text: str = message.get("text", "").strip()

    if not chat_id or not text.startswith("/start"):
        return {"ok": True}

    parts = text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) > 1 else None

    if not token:
        await _bot_reply(chat_id, (
            "Selamat datang di OJSDef Bot!\n\n"
            "Untuk menghubungkan akun, gunakan link yang diberikan oleh\n"
            "administrator OJSDef Anda, atau login ke dashboard dan\n"
            "buka halaman Setup Telegram."
        ))
        return {"ok": True}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(
                User.telegram_link_token == token,
                User.telegram_link_token_expires > datetime.now(timezone.utc),
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            await _bot_reply(chat_id, (
                "⚠️ Link tidak valid atau sudah kadaluarsa.\n\n"
                "Minta link baru kepada Administrator OJSDef Anda,\n"
                "atau login ke dashboard dan buka halaman\n"
                '"Setup Telegram" untuk mendapatkan link baru.\n\n'
                f"\U0001f310 {settings.frontend_base_url}/setup/telegram"
            ))
            return {"ok": True}

        user.telegram_chat_id = str(chat_id)
        user.notif_telegram = True
        user.telegram_link_token = None
        user.telegram_link_token_expires = None
        await session.commit()

        # Defer import to avoid circular import at module load
        from app.workers.notify import send_welcome
        send_welcome.apply_async((str(user.id),), queue="notifications")

        await _bot_reply(chat_id, (
            "✅ Akun berhasil terhubung ke OJSDef!\n\n"
            "Anda akan menerima notifikasi keamanan OJS\n"
            "secara otomatis melalui bot ini."
        ))

    return {"ok": True}
