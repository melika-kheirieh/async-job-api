import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.job_events import log_event
from app.models import Job, JobStatus
from app.repositories import JobRepository
from app.schemas import JobCreateRequest

STUCK_JOB_ERROR_MESSAGE = "Job timed out while running"
DEFAULT_STUCK_JOB_TIMEOUT_MINUTES = 10


class JobNotFoundError(Exception):
    def __init__(self, job_id: int):
        self.job_id = job_id
        super().__init__(f"Job {job_id} was not found.")


class JobService:
    def __init__(
        self,
        repository: JobRepository,
        enqueue_job: Callable[[int], None] | None = None,
    ):
        self.repository = repository
        self.enqueue_job = enqueue_job

    def create_job(self, job_create: JobCreateRequest) -> Job:
        if job_create.idempotency_key is not None:
            existing_job = self.repository.get_by_idempotency_key(
                job_create.idempotency_key,
            )
            if existing_job is not None:
                log_event(
                    logging.INFO,
                    "job_duplicate_request",
                    job_id=existing_job.id,
                    status=existing_job.status,
                    attempts=existing_job.attempts,
                    idempotency_key=existing_job.idempotency_key,
                )

                return existing_job

        try:
            job = self.repository.create(
                payload=job_create.payload,
                status=JobStatus.QUEUED,
                idempotency_key=job_create.idempotency_key,
            )
        except IntegrityError:
            self.repository.rollback()

            if job_create.idempotency_key is None:
                raise

            existing_job = self.repository.get_by_idempotency_key(
                job_create.idempotency_key,
            )
            if existing_job is None:
                raise

            log_event(
                logging.INFO,
                "job_duplicate_request",
                job_id=existing_job.id,
                status=existing_job.status,
                attempts=existing_job.attempts,
                idempotency_key=existing_job.idempotency_key,
            )

            return existing_job

        log_event(
            logging.INFO,
            "job_created",
            job_id=job.id,
            status=job.status,
            attempts=job.attempts,
            idempotency_key=job.idempotency_key,
        )

        if self.enqueue_job is not None:
            self.enqueue_job(job.id)

        return job

    def get_job(self, job_id: int) -> Job:
        job = self.repository.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Job], int]:
        jobs = self.repository.list_jobs(
            status=status,
            limit=limit,
            offset=offset,
        )
        count = self.repository.count_jobs(status=status)

        return jobs, count

    def claim_job_for_processing(self, job_id: int) -> Job | None:
        job = self.repository.claim_job_for_processing(job_id)
        if job is not None:
            return job

        existing_job = self.repository.get_by_id(job_id)
        if existing_job is None:
            raise JobNotFoundError(job_id)

        return None

    def mark_retrying(self, job_id: int, error_message: str) -> Job:
        job = self.repository.mark_retrying(
            job_id=job_id,
            error_message=error_message,
        )
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def mark_completed(self, job_id: int, result: dict[str, Any]) -> Job:
        job = self.repository.mark_completed(
            job_id=job_id,
            result=result,
        )
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def mark_failed(self, job_id: int, error_message: str) -> Job:
        job = self.repository.mark_failed(
            job_id=job_id,
            error_message=error_message,
        )
        if job is None:
            raise JobNotFoundError(job_id)
        return job


    def recover_stuck_jobs(
    self,
    timeout_minutes: int = DEFAULT_STUCK_JOB_TIMEOUT_MINUTES,
    ) -> list[Job]:
        stuck_jobs = self.repository.list_stuck_running_jobs(
            timeout_minutes=timeout_minutes,
        )

        recovered_jobs: list[Job] = []

        for job in stuck_jobs:
            if job.started_at is None:
                continue

            recovered_job = self.repository.mark_stuck_job_failed(
                job_id=job.id,
                expected_started_at=job.started_at,
                error_message=STUCK_JOB_ERROR_MESSAGE,
            )

            if recovered_job is None:
                continue

            log_event(
                logging.WARNING,
                "stuck_job_recovered",
                job_id=recovered_job.id,
                status=recovered_job.status,
                attempts=recovered_job.attempts,
                error_type="StuckJobTimeout",
            )

            recovered_jobs.append(recovered_job)

        return recovered_jobs
