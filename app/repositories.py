from typing import Any

from sqlalchemy.orm import Session

from app.models import Job, JobStatus


class JobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, payload: dict[str, Any], status: JobStatus = JobStatus.QUEUED) -> Job:
        job = Job(
            payload=payload,
            status=status,
        )

        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        return job

    def get_by_id(self, job_id: int) -> Job | None:
        return self.db.get(Job, job_id)

    def mark_running(self, job_id: int) -> Job | None:
        return self._update_state(
            job_id=job_id,
            status=JobStatus.RUNNING,
            result=None,
            error_message=None,
        )

    def mark_completed(self, job_id: int, result: dict[str, Any]) -> Job | None:
        return self._update_state(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            result=result,
            error_message=None,
        )

    def mark_failed(self, job_id: int, error_message: str) -> Job | None:
        return self._update_state(
            job_id=job_id,
            status=JobStatus.FAILED,
            result=None,
            error_message=error_message,
        )

    def _update_state(
        self,
        job_id: int,
        status: JobStatus,
        result: dict[str, Any] | None,
        error_message: str | None,
    ) -> Job | None:
        job = self.get_by_id(job_id)

        if job is None:
            return None

        job.status = status
        job.result = result
        job.error_message = error_message

        self.db.commit()
        self.db.refresh(job)

        return job