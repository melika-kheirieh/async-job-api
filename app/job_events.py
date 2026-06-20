import logging
import time
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
    exc_info: bool = False,
    **fields: Any,
) -> None:
    ts = time.time()

    parts = [
        f"ts={ts}",
        f"event={event}",
    ]

    if trace_id is not None:
        parts.append(f"trace_id={trace_id}")

    if job_id is not None:
        parts.append(f"job_id={job_id}")

    for key, value in fields.items():
        if value is None:
            continue

        parts.append(f"{key}={_fmt(value)}")

    logger.log(
        level,
        " ".join(parts),
        exc_info=exc_info,
    )
