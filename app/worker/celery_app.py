from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "ojsdef_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.task_routes = {
    "app.worker.tasks.internal.*": {"queue": "internal_scan"},
    "app.worker.tasks.external.*": {"queue": "external_scan"},
    "app.worker.tasks.scoring.*": {"queue": "scoring"},
    "app.worker.tasks.notify.*": {"queue": "notifications"},
}

# Optional configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
