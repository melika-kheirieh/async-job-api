import logging

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db import SessionLocal
from app.repositories import JobRepository
from app.services import JobNotFoundError, JobService

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_RETRY_COUNTDOWN_SECONDS = 30


class RetryableJobError(Exception):
    """Raised when a job failed because of a temporary condition."""


class NonRetryableJobError(Exception):
    """Raised when retrying the job would not make the failure go away."""


def get_retry_countdown(retry_number: int) -> int:
    return min(2**retry_number, MAX_RETRY_COUNTDOWN_SECONDS)


def build_job_result(payload: dict) -> dict:
    if payload.get("fail") is True:
        raise NonRetryableJobError("Forced failure requested by payload")

    if payload.get("transient_fail") is True:
        raise RetryableJobError("Transient failure requested by payload")

    return {
        "processed": True,
        "input_size": len(str(payload)),
        "message": "Job completed successfully",
    }


def process_job_by_id(job_id: int, db: Session) -> None:
    repository = JobRepository(db)
    service = JobService(repository)

    try:
        job = service.claim_job_for_processing(job_id)
    except JobNotFoundError:
        logger.warning("Job not found: job_id=%s", job_id)
        return

    if job is None:
        skipped_job = service.get_job(job_id)
        logger.info(
            "Skipping unclaimable job: job_id=%s status=%s",
            job_id,
            skipped_job.status,
        )
        return

    logger.info("Starting job processing: job_id=%s", job_id)

    payload = job.payload

    try:
        result = build_job_result(payload)
        service.mark_completed(job_id, result)
        logger.info("Job completed: job_id=%s", job_id)

    except RetryableJobError:
        logger.warning("Job failed with retryable error: job_id=%s", job_id)
        raise

    except NonRetryableJobError as exc:
        service.mark_failed(job_id, str(exc))
        logger.warning(
            "Job failed with non-retryable error: job_id=%s error=%s",
            job_id,
            exc,
        )

    except Exception as exc:
        service.mark_failed(job_id, str(exc))
        logger.exception("Job failed with unexpected error: job_id=%s", job_id)


@celery_app.task(
    name="process_job",
    bind=True,
    max_retries=MAX_RETRIES,
)
def process_job(self, job_id: int) -> None:
    db = SessionLocal()

    try:
        process_job_by_id(job_id, db)

    except RetryableJobError as exc:
        repository = JobRepository(db)
        service = JobService(repository)

        if self.request.retries >= MAX_RETRIES:
            error_message = f"Retryable failure exceeded max retries: {exc}"

            try:
                service.mark_failed(job_id, error_message)
            except JobNotFoundError:
                logger.warning(
                    "Could not mark retried job as failed because it was not found: job_id=%s",
                    job_id,
                )
                return

            logger.warning(
                "Job failed after retries: job_id=%s retries=%s error=%s",
                job_id,
                self.request.retries,
                exc,
            )
            return

        countdown = get_retry_countdown(self.request.retries)

        logger.warning(
            "Retrying job: job_id=%s retry=%s countdown=%s error=%s",
            job_id,
            self.request.retries + 1,
            countdown,
            exc,
        )

        raise self.retry(exc=exc, countdown=countdown)

    finally:
        db.close()