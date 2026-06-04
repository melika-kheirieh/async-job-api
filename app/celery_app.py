import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "async_job_api",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_track_started=True,
)