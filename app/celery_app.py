from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery("ojsdef", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Jakarta",
    enable_utc=True,
    task_always_eager=False,
    broker_connection_retry_on_startup=True,
    include=[
        "app.workers.internal_bot",
        "app.workers.external_bot",
        "app.workers.scoring",
        "app.workers.notify",
    ],
    task_routes={
        "app.workers.internal_bot.*": {"queue": "internal_scan"},
        "app.workers.external_bot.*": {"queue": "external_scan"},
        "app.workers.scoring.*":      {"queue": "scoring"},
        "app.workers.notify.*":       {"queue": "notifications"},
    },
)
