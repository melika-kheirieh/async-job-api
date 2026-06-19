from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models import JobStatus


class JobCreateRequest(BaseModel):
    payload: dict[str, Any]
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )


class JobResponse(BaseModel):
    id: int
    status: JobStatus
    idempotency_key: str | None
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    attempts: int
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
    }


class JobListResponse(BaseModel):
    items: list[JobResponse]
    limit: int
    offset: int
    count: int