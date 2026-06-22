from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Job, JobStatus

CLAIMABLE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RETRYING)


class JobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        payload: dict[str, Any],
        status: JobStatus = JobStatus.QUEUED,
        idempotency_key: str | None = None,
    ) -> Job:
        job = Job(
            payload=payload,
            status=status,
            idempotency_key=idempotency_key,
        )

        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        return job

    def rollback(self) -> None:
        self.db.rollback()

    def get_by_id(self, job_id: int) -> Job | None:
        return self.db.get(Job, job_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        return (
            self.db.query(Job)
            .filter(Job.idempotency_key == idempotency_key)
            .one_or_none()
        )

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Job]:
        query = self.db.query(Job)

        if status is not None:
            query = query.filter(Job.status == status)

        return (
            query.order_by(Job.created_at.desc(), Job.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_jobs(self, status: JobStatus | None = None) -> int:
        query = self.db.query(Job)

        if status is not None:
            query = query.filter(Job.status == status)

        return query.count()

    def list_stuck_running_jobs(self, timeout_minutes: int) -> list[Job]:
        cutoff = datetime.now(UTC) - timedelta(minutes=timeout_minutes)

        return (
            self.db.query(Job)
            .filter(Job.status == JobStatus.RUNNING)
            .filter(Job.started_at.is_not(None))
            .filter(Job.started_at < cutoff)
            .all()
        )
    
    def mark_stuck_job_failed(
        self,
        job_id: int,
        expected_started_at: datetime,
        error_message: str,
    ) -> Job | None:
        now = datetime.now(UTC)

        result = self.db.execute(
            update(Job)
            .where(Job.id == job_id)
            .where(Job.status == JobStatus.RUNNING)
            .where(Job.started_at == expected_started_at)
            .values(
                status=JobStatus.FAILED,
                result=None,
                error_message=error_message,
                completed_at=None,
                failed_at=now,
            )
        )

        if result.rowcount == 0:
            self.db.rollback()
            return None

        self.db.commit()

        recovered_job = self.get_by_id(job_id)
        if recovered_job is None:
            raise RuntimeError(
                "Recovered job disappeared before it could be loaded."
            )

        return recovered_job

    def claim_job_for_processing(self, job_id: int) -> Job | None:
        now = datetime.now(UTC)

        result = self.db.execute(
            update(Job)
            .where(Job.id == job_id)
            .where(Job.status.in_(CLAIMABLE_JOB_STATUSES))
            .values(
                status=JobStatus.RUNNING,
                attempts=Job.attempts + 1,
                started_at=now,
                completed_at=None,
                failed_at=None,
                error_message=None,
                result=None,
            )
        )

        if result.rowcount == 0:
            self.db.rollback()
            return None

        self.db.commit()

        claimed_job = self.get_by_id(job_id)
        if claimed_job is None:
            raise RuntimeError("Claimed job disappeared before it could be loaded.")

        return claimed_job

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

    def mark_retrying(self, job_id: int, error_message: str) -> Job | None:
        job = self.get_by_id(job_id)
        if job is None:
            return None

        job.status = JobStatus.RETRYING
        job.result = None
        job.error_message = error_message
        job.completed_at = None
        job.failed_at = None

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