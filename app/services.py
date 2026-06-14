from collections.abc import Callable
from typing import Any

from app.models import Job, JobStatus
from app.repositories import JobRepository
from app.schemas import JobCreateRequest


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
        job = self.repository.create(
            payload=job_create.payload,
            status=JobStatus.QUEUED,
        )

        if self.enqueue_job is not None:
            self.enqueue_job(job.id)

        return job

    def get_job(self, job_id: int) -> Job:
        job = self.repository.get_by_id(job_id)

        if job is None:
            raise JobNotFoundError(job_id)

        return job

    def mark_running(self, job_id: int) -> Job:
        job = self.repository.mark_running(job_id)

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