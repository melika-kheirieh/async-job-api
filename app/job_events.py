import logging
import time
import uuid
from enum import Enum
from typing import Any

logger = logging.getLogger("app.job_events")


def _fmt(value: Any) -> str:
    if isinstance(value, Enum):
        return value.value
    return str(value)


def log_event(
    level: int,
    event: str,
    *,
    job_id: int | None = None,
    trace_id: str | None = None,
    **fields: Any,
) -> None:

    if trace_id is None:
        trace_id = str(uuid.uuid4())

    ts = time.time()

    parts = [
        f"ts={ts}",
        f"event={event}",
        f"trace_id={trace_id}",
    ]

    if job_id is not None:
        parts.append(f"job_id={job_id}")

    for k, v in fields.items():
        if v is None:
            continue
        parts.append(f"{k}={_fmt(v)}")

    logger.log(level, " ".join(parts))