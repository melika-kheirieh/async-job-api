from celery import Celery

from app.config import get_settings


settings = get_settings()

celery_app = Celery(
    "async_job_api",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
)