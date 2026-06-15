import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    celery_broker_url: str
    celery_result_backend: str


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./jobs.db"),
        celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    )