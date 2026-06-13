import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import JobStatus
from app.repositories import JobRepository
from app.schemas import JobCreateRequest
from app.services import JobService
from app.tasks import process_job_by_id


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