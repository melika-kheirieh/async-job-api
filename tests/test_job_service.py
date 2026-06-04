import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import JobStatus
from app.repositories import JobRepository
from app.schemas import JobCreateRequest
from app.services import JobNotFoundError, JobService


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


def test_mark_running_updates_job_status(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    updated_job = job_service.mark_running(job.id)

    assert updated_job.status == JobStatus.RUNNING
    assert updated_job.result is None
    assert updated_job.error_message is None


def test_mark_completed_stores_result(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    result = {
        "processed": True,
        "message": "Job completed successfully",
    }

    updated_job = job_service.mark_completed(job.id, result)

    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.result == result
    assert updated_job.error_message is None


def test_mark_failed_stores_error_message(job_service):
    job = job_service.create_job(
        JobCreateRequest(payload={"text": "hello backend"})
    )

    updated_job = job_service.mark_failed(
        job.id,
        "Something went wrong",
    )

    assert updated_job.status == JobStatus.FAILED
    assert updated_job.result is None
    assert updated_job.error_message == "Something went wrong"


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