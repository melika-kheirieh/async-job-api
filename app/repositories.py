from datetime import UTC, datetime, timedelta
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

    def list_stuck_running_jobs(self, timeout_minutes: int) -> list[Job]:
        cutoff = datetime.now(UTC) - timedelta(minutes=timeout_minutes)

        return (
            self.db.query(Job)
            .filter(Job.status == JobStatus.RUNNING)
            .filter(Job.started_at.is_not(None))
            .filter(Job.started_at < cutoff)
            .all()
        )

    def mark_running(self, job_id: int) -> Job | None:
        job = self.get_by_id(job_id)

        if job is None:
            return None

        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        job.completed_at = None
        job.failed_at = None
        job.error_message = None
        job.result = None

        self.db.commit()
        self.db.refresh(job)

        return job

    def mark_completed(self, job_id: int, result: dict[str, Any]) -> Job | None:
        job = self.get_by_id(job_id)

        if job is None:
            return None

        job.status = JobStatus.COMPLETED
        job.result = result
        job.error_message = None
        job.completed_at = datetime.now(UTC)
        job.failed_at = None

        self.db.commit()
        self.db.refresh(job)

        return job

    def mark_failed(self, job_id: int, error_message: str) -> Job | None:
        job = self.get_by_id(job_id)

        if job is None:
            return None

        job.status = JobStatus.FAILED
        job.result = None
        job.error_message = error_message
        job.failed_at = datetime.now(UTC)

        self.db.commit()
        self.db.refresh(job)

        return job