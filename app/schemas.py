from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models import JobStatus

class JobCreateRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)

class JobResponse(BaseModel):
    id: int
    status: JobStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
    }   