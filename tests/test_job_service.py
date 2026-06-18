from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import JobStatus
from app.repositories import JobRepository
from app.schemas import JobCreateRequest
from app.services import STUCK_JOB_ERROR_MESSAGE, JobNotFoundError, JobService


@pytest.fixture()
def job_service():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )

    Base.metadata.create_all(bind=test_engine)

    db = TestingSessionLocal()
    repository = JobRepository(db)
    service = JobService(repository)

    try:
        yield service
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_new_job_starts_as_queued(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    assert job.status == JobStatus.QUEUED
    assert job.result is None
    assert job.error_message is None
    assert job.attempts == 0
    assert job.started_at is None
    assert job.completed_at is None
    assert job.failed_at is None


def test_mark_running_updates_job_status(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    updated_job = job_service.mark_running(job.id)

    assert updated_job.status == JobStatus.RUNNING
    assert updated_job.result is None
    assert updated_job.error_message is None
    assert updated_job.attempts == 1
    assert updated_job.started_at is not None
    assert updated_job.completed_at is None
    assert updated_job.failed_at is None


def test_mark_completed_stores_result(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    job_service.mark_running(job.id)

    result = {
        "processed": True,
        "message": "Job completed successfully",
    }

    updated_job = job_service.mark_completed(job.id, result)

    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.result == result
    assert updated_job.error_message is None
    assert updated_job.attempts == 1
    assert updated_job.started_at is not None
    assert updated_job.completed_at is not None
    assert updated_job.failed_at is None


def test_mark_failed_stores_error_message(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    job_service.mark_running(job.id)

    updated_job = job_service.mark_failed(
        job.id,
        "Something went wrong",
    )

    assert updated_job.status == JobStatus.FAILED
    assert updated_job.result is None
    assert updated_job.error_message == "Something went wrong"
    assert updated_job.attempts == 1
    assert updated_job.started_at is not None
    assert updated_job.completed_at is None
    assert updated_job.failed_at is not None


def test_mark_running_missing_job_raises_not_found(job_service):
    with pytest.raises(JobNotFoundError):
        job_service.mark_running(999999)


def test_mark_completed_missing_job_raises_not_found(job_service):
    with pytest.raises(JobNotFoundError):
        job_service.mark_completed(
            999999,
            {"processed": True},
        )


def test_mark_failed_missing_job_raises_not_found(job_service):
    with pytest.raises(JobNotFoundError):
        job_service.mark_failed(
            999999,
            "Something went wrong",
        )


def test_create_job_calls_enqueue_with_created_job_id():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )

    Base.metadata.create_all(bind=test_engine)

    db = TestingSessionLocal()
    enqueued_job_ids = []

    try:
        repository = JobRepository(db)
        service = JobService(
            repository,
            enqueue_job=enqueued_job_ids.append,
        )

        job = service.create_job(
            JobCreateRequest(payload={"text": "hello backend"})
        )

        assert enqueued_job_ids == [job.id]

    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_recover_stuck_jobs_marks_old_running_job_as_failed(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "old running job"})
    )

    running_job = job_service.mark_running(job.id)
    running_job.started_at = datetime.now(UTC) - timedelta(minutes=30)
    job_service.repository.db.commit()

    recovered_jobs = job_service.recover_stuck_jobs(timeout_minutes=10)

    assert len(recovered_jobs) == 1
    assert recovered_jobs[0].id == job.id
    assert recovered_jobs[0].status == JobStatus.FAILED
    assert recovered_jobs[0].error_message == STUCK_JOB_ERROR_MESSAGE
    assert recovered_jobs[0].failed_at is not None

    updated_job = job_service.get_job(job.id)

    assert updated_job.status == JobStatus.FAILED
    assert updated_job.error_message == STUCK_JOB_ERROR_MESSAGE
    assert updated_job.failed_at is not None


def test_recover_stuck_jobs_leaves_recent_running_job_untouched(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "recent running job"})
    )

    job_service.mark_running(job.id)

    recovered_jobs = job_service.recover_stuck_jobs(timeout_minutes=10)

    assert recovered_jobs == []

    updated_job = job_service.get_job(job.id)

    assert updated_job.status == JobStatus.RUNNING
    assert updated_job.error_message is None
    assert updated_job.failed_at is None


def test_recover_stuck_jobs_leaves_terminal_jobs_untouched(job_service):
    completed_job = job_service.create_job(
        JobCreateRequest(payload={"text": "completed job"})
    )
    job_service.mark_running(completed_job.id)
    job_service.mark_completed(
        completed_job.id,
        {
            "processed": True,
            "message": "Job completed successfully",
        },
    )

    failed_job = job_service.create_job(
        JobCreateRequest(payload={"text": "failed job"})
    )
    job_service.mark_running(failed_job.id)
    job_service.mark_failed(
        failed_job.id,
        "Already failed",
    )

    recovered_jobs = job_service.recover_stuck_jobs(timeout_minutes=10)

    assert recovered_jobs == []

    updated_completed_job = job_service.get_job(completed_job.id)
    assert updated_completed_job.status == JobStatus.COMPLETED
    assert updated_completed_job.result == {
        "processed": True,
        "message": "Job completed successfully",
    }
    assert updated_completed_job.error_message is None

    updated_failed_job = job_service.get_job(failed_job.id)
    assert updated_failed_job.status == JobStatus.FAILED
    assert updated_failed_job.error_message == "Already failed"