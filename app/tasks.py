import logging

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db import SessionLocal
from app.job_events import log_event
from app.repositories import JobRepository
from app.services import JobNotFoundError, JobService

MAX_RETRIES = 3
MAX_RETRY_COUNTDOWN_SECONDS = 30


class RetryableJobError(Exception):
    pass


class NonRetryableJobError(Exception):
    pass


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
        log_event(logging.WARNING, "job_not_found", job_id=job_id)
        return

    if job is None:
        skipped_job = service.get_job(job_id)

        log_event(
            logging.INFO,
            "job_skipped",
            job_id=job_id,
            status=skipped_job.status,
            attempts=skipped_job.attempts,
            reason="unclaimable",
        )
        return

    log_event(
        logging.INFO,
        "job_claimed",
        job_id=job.id,
        status=job.status,
        attempts=job.attempts,
    )

    try:
        result = build_job_result(job.payload)

        completed_job = service.mark_completed(job_id, result)

        log_event(
            logging.INFO,
            "job_completed",
            job_id=completed_job.id,
            status=completed_job.status,
            attempts=completed_job.attempts,
        )

    except RetryableJobError as exc:
        retrying_job = service.mark_retrying(job_id, str(exc))

        log_event(
            logging.WARNING,
            "job_retrying",
            job_id=retrying_job.id,
            status=retrying_job.status,
            attempts=retrying_job.attempts,
            error_type=type(exc).__name__,
        )

        raise

    except NonRetryableJobError as exc:
        failed_job = service.mark_failed(job_id, str(exc))

        log_event(
            logging.WARNING,
            "job_failed",
            job_id=failed_job.id,
            status=failed_job.status,
            attempts=failed_job.attempts,
            error_type=type(exc).__name__,
        )

    except Exception as exc:
        failed_job = service.mark_failed(job_id, str(exc))

        log_event(
            logging.ERROR,
            "job_failed",
            job_id=failed_job.id,
            status=failed_job.status,
            attempts=failed_job.attempts,
            error_type=type(exc).__name__,
            exc_info=True,
        )


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
                failed_job = service.mark_failed(job_id, error_message)
            except JobNotFoundError:
                log_event(logging.WARNING, "job_not_found", job_id=job_id)
                return

            log_event(
                logging.WARNING,
                "job_failed",
                job_id=failed_job.id,
                status=failed_job.status,
                attempts=failed_job.attempts,
                error_type=type(exc).__name__,
                retries=self.request.retries,
                reason="retry_limit_exceeded",
            )
            return

        countdown = get_retry_countdown(self.request.retries)
        retrying_job = service.get_job(job_id)

        log_event(
            logging.WARNING,
            "job_retry_scheduled",
            job_id=retrying_job.id,
            status=retrying_job.status,
            attempts=retrying_job.attempts,
            error_type=type(exc).__name__,
            retry=self.request.retries + 1,
            countdown=countdown,
        )

        raise self.retry(exc=exc, countdown=countdown)

    finally:
        db.close()
