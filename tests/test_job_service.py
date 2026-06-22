from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Job, JobStatus
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


def claim_job(job_service: JobService, job_id: int) -> Job:
    claimed_job = job_service.claim_job_for_processing(job_id)
    assert claimed_job is not None
    return claimed_job


def test_new_job_starts_as_queued(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    assert job.status == JobStatus.QUEUED
    assert job.idempotency_key is None
    assert job.result is None
    assert job.error_message is None
    assert job.attempts == 0
    assert job.started_at is None
    assert job.completed_at is None
    assert job.failed_at is None


def test_create_job_stores_idempotency_key(job_service):
    job = job_service.create_job(
        JobCreateRequest(
            payload={"text": "hello backend"},
            idempotency_key="request-123",
        )
    )

    assert job.status == JobStatus.QUEUED
    assert job.idempotency_key == "request-123"
    assert job.payload == {"text": "hello backend"}


def test_create_job_with_same_idempotency_key_returns_existing_job(job_service):
    first_job = job_service.create_job(
        JobCreateRequest(
            payload={"text": "hello backend"},
            idempotency_key="request-123",
        )
    )

    second_job = job_service.create_job(
        JobCreateRequest(
            payload={"text": "hello backend"},
            idempotency_key="request-123",
        )
    )

    assert second_job.id == first_job.id
    assert second_job.idempotency_key == "request-123"
    assert second_job.payload == {"text": "hello backend"}


def test_create_job_without_idempotency_key_creates_separate_jobs(job_service):
    first_job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )
    second_job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    assert second_job.id != first_job.id
    assert first_job.idempotency_key is None
    assert second_job.idempotency_key is None


def test_duplicate_idempotency_key_does_not_enqueue_again():
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

        first_job = service.create_job(
            JobCreateRequest(
                payload={"text": "hello backend"},
                idempotency_key="request-123",
            )
        )
        second_job = service.create_job(
            JobCreateRequest(
                payload={"text": "hello backend"},
                idempotency_key="request-123",
            )
        )

        assert second_job.id == first_job.id
        assert enqueued_job_ids == [first_job.id]
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_claim_queued_job_marks_it_as_running(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    claimed_job = job_service.claim_job_for_processing(job.id)

    assert claimed_job is not None
    assert claimed_job.status == JobStatus.RUNNING
    assert claimed_job.attempts == 1
    assert claimed_job.started_at is not None
    assert claimed_job.completed_at is None
    assert claimed_job.failed_at is None
    assert claimed_job.result is None
    assert claimed_job.error_message is None


def test_mark_retrying_updates_job_status(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "temporary problem"})
    )

    running_job = claim_job(job_service, job.id)
    retrying_job = job_service.mark_retrying(job.id, "Temporary failure")

    assert retrying_job.status == JobStatus.RETRYING
    assert retrying_job.result is None
    assert retrying_job.error_message == "Temporary failure"
    assert retrying_job.attempts == running_job.attempts
    assert retrying_job.started_at is not None
    assert retrying_job.completed_at is None
    assert retrying_job.failed_at is None


def test_claim_retrying_job_marks_it_as_running(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "temporary problem"})
    )

    claim_job(job_service, job.id)
    job_service.mark_retrying(job.id, "Temporary failure")

    claimed_job = job_service.claim_job_for_processing(job.id)

    assert claimed_job is not None
    assert claimed_job.status == JobStatus.RUNNING
    assert claimed_job.attempts == 2
    assert claimed_job.started_at is not None
    assert claimed_job.completed_at is None
    assert claimed_job.failed_at is None
    assert claimed_job.result is None
    assert claimed_job.error_message is None


def test_claim_running_job_returns_none_without_incrementing_attempts(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    running_job = claim_job(job_service, job.id)

    claimed_job = job_service.claim_job_for_processing(job.id)
    updated_job = job_service.get_job(job.id)

    assert claimed_job is None
    assert updated_job.status == JobStatus.RUNNING
    assert updated_job.attempts == running_job.attempts


def test_claim_completed_job_returns_none_without_changing_state(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "already completed"})
    )
    result = {"processed": True}

    job_service.mark_completed(job.id, result)

    claimed_job = job_service.claim_job_for_processing(job.id)
    updated_job = job_service.get_job(job.id)

    assert claimed_job is None
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.result == result
    assert updated_job.attempts == 0


def test_claim_failed_job_returns_none_without_changing_state(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "already failed"})
    )

    job_service.mark_failed(job.id, "Already failed")

    claimed_job = job_service.claim_job_for_processing(job.id)
    updated_job = job_service.get_job(job.id)

    assert claimed_job is None
    assert updated_job.status == JobStatus.FAILED
    assert updated_job.error_message == "Already failed"
    assert updated_job.attempts == 0


def test_claim_missing_job_raises_not_found(job_service):
    with pytest.raises(JobNotFoundError):
        job_service.claim_job_for_processing(999999)


def test_mark_completed_stores_result(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )
    claim_job(job_service, job.id)

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
    claim_job(job_service, job.id)

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


def test_mark_retrying_missing_job_raises_not_found(job_service):
    with pytest.raises(JobNotFoundError):
        job_service.mark_retrying(999999, "Temporary failure")


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
    running_job = claim_job(job_service, job.id)

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

    claim_job(job_service, job.id)

    recovered_jobs = job_service.recover_stuck_jobs(timeout_minutes=10)
    updated_job = job_service.get_job(job.id)

    assert recovered_jobs == []
    assert updated_job.status == JobStatus.RUNNING
    assert updated_job.error_message is None
    assert updated_job.failed_at is None


def test_recover_stuck_jobs_leaves_retrying_job_untouched(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "retrying job"})
    )

    claim_job(job_service, job.id)
    retrying_job = job_service.mark_retrying(job.id, "Temporary failure")
    retrying_job.started_at = datetime.now(UTC) - timedelta(minutes=30)
    job_service.repository.db.commit()

    recovered_jobs = job_service.recover_stuck_jobs(timeout_minutes=10)
    updated_job = job_service.get_job(job.id)

    assert recovered_jobs == []
    assert updated_job.status == JobStatus.RETRYING
    assert updated_job.error_message == "Temporary failure"
    assert updated_job.failed_at is None


def test_recover_stuck_jobs_leaves_terminal_jobs_untouched(job_service):
    completed_job = job_service.create_job(
        JobCreateRequest(payload={"text": "completed job"})
    )
    claim_job(job_service, completed_job.id)
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
    claim_job(job_service, failed_job.id)
    job_service.mark_failed(
        failed_job.id,
        "Already failed",
    )

    recovered_jobs = job_service.recover_stuck_jobs(timeout_minutes=10)

    assert recovered_jobs == []


def test_stuck_recovery_does_not_overwrite_completed_job(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "finishing job"})
    )
    running_job = claim_job(job_service, job.id)
    running_job.started_at = datetime.now(UTC) - timedelta(minutes=30)
    job_service.repository.db.commit()

    expected_started_at = running_job.started_at
    completed_result = {"processed": True}
    job_service.mark_completed(job.id, completed_result)

    recovered_job = job_service.repository.mark_stuck_job_failed(
        job_id=job.id,
        expected_started_at=expected_started_at,
        error_message=STUCK_JOB_ERROR_MESSAGE,
    )

    assert recovered_job is None

    updated_job = job_service.get_job(job.id)
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.result == completed_result
    assert updated_job.error_message is None
    assert updated_job.failed_at is None


def test_stuck_recovery_does_not_overwrite_newer_attempt(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "retried job"})
    )
    running_job = claim_job(job_service, job.id)
    running_job.started_at = datetime.now(UTC) - timedelta(minutes=30)
    job_service.repository.db.commit()

    expected_started_at = running_job.started_at

    job_service.mark_retrying(job.id, "Temporary failure")
    newer_attempt = job_service.claim_job_for_processing(job.id)

    assert newer_attempt is not None
    assert newer_attempt.attempts == 2
    assert newer_attempt.started_at != expected_started_at

    recovered_job = job_service.repository.mark_stuck_job_failed(
        job_id=job.id,
        expected_started_at=expected_started_at,
        error_message=STUCK_JOB_ERROR_MESSAGE,
    )

    assert recovered_job is None

    updated_job = job_service.get_job(job.id)
    assert updated_job.status == JobStatus.RUNNING
    assert updated_job.attempts == 2
    assert updated_job.error_message is None
    assert updated_job.failed_at is None
