import logging

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models import JobStatus
from app.repositories import JobRepository
from app.services import JobNotFoundError, JobService


logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED}


def process_job_by_id(job_id: int, db: Session) -> None:
    repository = JobRepository(db)
    service = JobService(repository)

    try:
        job = service.get_job(job_id)
    except JobNotFoundError:
        logger.warning("Job not found: job_id=%s", job_id)
        return

    if job.status in TERMINAL_STATUSES:
        logger.info(
            "Skipping terminal job: job_id=%s status=%s",
            job_id,
            job.status,
        )
        return

    logger.info("Starting job processing: job_id=%s", job_id)

    job = service.mark_running(job_id)
    payload = job.payload

    try:
        if payload.get("fail") is True:
            raise ValueError("Forced failure requested by payload")

        result = {
            "processed": True,
            "input_size": len(str(payload)),
            "message": "Job completed successfully",
        }

        service.mark_completed(job_id, result)
        logger.info("Job completed: job_id=%s", job_id)

    except Exception as exc:
        service.mark_failed(job_id, str(exc))
        logger.warning("Job failed: job_id=%s error=%s", job_id, exc)


@celery_app.task(name="process_job")
def process_job(job_id: int) -> None:
    db = SessionLocal()

    try:
        process_job_by_id(job_id, db)
    finally:
        db.close()