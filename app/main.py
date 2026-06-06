import logging
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
import boto3
import httpx
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import get_settings
from app.database import engine
from sqlalchemy import text

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        pass
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
    except Exception:
        pass
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )
        try:
            s3.head_bucket(Bucket=settings.minio_bucket)
        except ClientError:
            s3.create_bucket(Bucket=settings.minio_bucket)
    except Exception:
        pass
    # Telegram webhook registration (non-fatal if it fails)
    if settings.telegram_bot_token and settings.telegram_webhook_secret:
        webhook_url = f"{settings.app_base_url}/telegram/webhook"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/setWebhook",
                    json={"url": webhook_url, "secret_token": settings.telegram_webhook_secret},
                )
            logger.info("Telegram webhook registered: %s", webhook_url)
        except Exception as e:
            logger.warning("Telegram webhook registration failed (non-fatal): %s", e)
    yield


app = FastAPI(
    title="OJSDef API", version="1.0.0", lifespan=lifespan,
    docs_url="/docs" if settings.environment == "development" else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

from app.middleware.auth import jwt_middleware
from app.middleware.plugin_auth import plugin_auth_middleware

app.add_middleware(BaseHTTPMiddleware, dispatch=plugin_auth_middleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=jwt_middleware)

if settings.sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(dsn=settings.sentry_dsn)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


from app.routers import auth as auth_router
from app.routers import targets as targets_router
from app.routers import scans as scans_router
from app.routers import reports as reports_router
from app.routers import dashboard as dashboard_router
from app.routers import admin as admin_router
from app.routers import plugin_callback as plugin_router
from app.routers.audit_logs import router as audit_logs_router
from app.routers import telegram_bot as telegram_bot_router

app.include_router(auth_router.router)
app.include_router(targets_router.router)
app.include_router(scans_router.router)
app.include_router(reports_router.router)
app.include_router(dashboard_router.router)
app.include_router(admin_router.router)
app.include_router(plugin_router.router)
app.include_router(audit_logs_router)
app.include_router(telegram_bot_router.router)
