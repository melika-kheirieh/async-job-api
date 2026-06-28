import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import JobStatus
from app.processors import RetryableJobError
from app.repositories import JobRepository
from app.schemas import JobCreateRequest
from app.services import JobService
from app.tasks import get_retry_countdown, process_job_by_id


@pytest.fixture()
def db_session():
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

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_worker_marks_job_as_completed(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    process_job_by_id(job.id, db_session)

    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.result == {
        "processed": True,
        "input_size": len(str({"text": "hello backend"})),
        "message": "Job completed successfully",
    }
    assert updated_job.error_message is None
    assert updated_job.attempts == 1
    assert updated_job.started_at is not None
    assert updated_job.completed_at is not None
    assert updated_job.failed_at is None


def test_worker_marks_job_as_failed_when_payload_requests_failure(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(payload={"text": "fail case", "fail": True})
    )

    process_job_by_id(job.id, db_session)

    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.FAILED
    assert updated_job.result is None
    assert updated_job.error_message == "Forced failure requested by payload"
    assert updated_job.attempts == 1
    assert updated_job.started_at is not None
    assert updated_job.completed_at is None
    assert updated_job.failed_at is not None


def test_worker_marks_job_as_retrying_for_transient_failure(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(
            payload={"text": "temporary problem", "transient_fail": True}
        )
    )

    with pytest.raises(RetryableJobError):
        process_job_by_id(job.id, db_session)

    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.RETRYING
    assert updated_job.result is None
    assert updated_job.error_message == "Transient failure requested by payload"
    assert updated_job.attempts == 1
    assert updated_job.started_at is not None
    assert updated_job.completed_at is None
    assert updated_job.failed_at is None


def test_worker_can_process_retrying_job_on_next_attempt(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(payload={"text": "recoverable job"})
    )

    claimed_job = service.claim_job_for_processing(job.id)
    assert claimed_job is not None
    service.mark_retrying(job.id, "Temporary failure")

    process_job_by_id(job.id, db_session)

    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.result == {
        "processed": True,
        "input_size": len(str({"text": "recoverable job"})),
        "message": "Job completed successfully",
    }
    assert updated_job.error_message is None
    assert updated_job.attempts == 2
    assert updated_job.started_at is not None
    assert updated_job.completed_at is not None
    assert updated_job.failed_at is None


def test_worker_skips_terminal_completed_job(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(payload={"text": "already done"})
    )
    original_result = {
        "processed": True,
        "message": "Already completed",
    }

    service.mark_completed(job.id, original_result)

    process_job_by_id(job.id, db_session)

    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.result == original_result
    assert updated_job.error_message is None
    assert updated_job.attempts == 0
    assert updated_job.started_at is None
    assert updated_job.completed_at is not None
    assert updated_job.failed_at is None


def test_worker_skips_terminal_failed_job(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(payload={"text": "already failed"})
    )

    service.mark_failed(job.id, "Already failed")

    process_job_by_id(job.id, db_session)

    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.FAILED
    assert updated_job.result is None
    assert updated_job.error_message == "Already failed"
    assert updated_job.attempts == 0
    assert updated_job.started_at is None
    assert updated_job.completed_at is None
    assert updated_job.failed_at is not None


def test_worker_skips_running_job_without_incrementing_attempts(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(payload={"text": "already running"})
    )
    running_job = service.claim_job_for_processing(job.id)
    assert running_job is not None

    process_job_by_id(job.id, db_session)

    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.RUNNING
    assert updated_job.result is None
    assert updated_job.error_message is None
    assert updated_job.attempts == running_job.attempts
    assert updated_job.started_at is not None
    assert updated_job.completed_at is None
    assert updated_job.failed_at is None


def test_worker_skips_canceled_job_without_incrementing_attempts(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(payload={"text": "already canceled"})
    )
    canceled_job = service.cancel_job(job.id)

    process_job_by_id(job.id, db_session)

    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.CANCELED
    assert updated_job.result is None
    assert updated_job.error_message is None
    assert updated_job.attempts == canceled_job.attempts
    assert updated_job.started_at is None
    assert updated_job.completed_at is None
    assert updated_job.failed_at is None


def test_retry_countdown_uses_exponential_backoff_with_cap():
    assert get_retry_countdown(0) == 1
    assert get_retry_countdown(1) == 2
    assert get_retry_countdown(2) == 4
    assert get_retry_countdown(3) == 8
    assert get_retry_countdown(10) == 30


def test_duplicate_delivery_after_completed_job_does_not_reprocess(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    job = service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    process_job_by_id(job.id, db_session)
    completed_job = service.get_job(job.id)

    expected_result = {
        "processed": True,
        "input_size": len(str({"text": "hello backend"})),
        "message": "Job completed successfully",
    }

    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.attempts == 1
    assert completed_job.result == expected_result
    assert completed_job.error_message is None
    assert completed_job.completed_at is not None
    assert completed_job.failed_at is None

    completed_result = completed_job.result
    completed_at = completed_job.completed_at
    attempts = completed_job.attempts

    process_job_by_id(job.id, db_session)
    updated_job = service.get_job(job.id)

    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.result == completed_result
    assert updated_job.error_message is None
    assert updated_job.attempts == attempts
    assert updated_job.completed_at == completed_at
    assert updated_job.failed_at is None
