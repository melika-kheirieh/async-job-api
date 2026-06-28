from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli import recover_stuck_jobs as cli
from app.db import Base
from app.models import JobStatus
from app.repositories import JobRepository
from app.schemas import JobCreateRequest
from app.services import JobService, STUCK_JOB_ERROR_MESSAGE


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
        test_engine.dispose()


def test_recover_stuck_jobs_for_session_reports_recovered_jobs(db_session):
    repository = JobRepository(db_session)
    service = JobService(repository)

    stuck_job = service.create_job(
        JobCreateRequest(payload={"text": "old running job"})
    )
    recent_job = service.create_job(
        JobCreateRequest(payload={"text": "recent running job"})
    )

    stuck_running_job = service.claim_job_for_processing(stuck_job.id)
    recent_running_job = service.claim_job_for_processing(recent_job.id)

    assert stuck_running_job is not None
    assert recent_running_job is not None

    stuck_running_job.started_at = datetime.now(UTC) - timedelta(minutes=30)
    db_session.commit()

    result = cli.recover_stuck_jobs_for_session(
        db=db_session,
        timeout_minutes=10,
    )

    assert result.recovered_count == 1
    assert result.recovered_job_ids == [stuck_job.id]

    updated_stuck_job = service.get_job(stuck_job.id)
    updated_recent_job = service.get_job(recent_job.id)

    assert updated_stuck_job.status == JobStatus.FAILED
    assert updated_stuck_job.error_message == STUCK_JOB_ERROR_MESSAGE
    assert updated_recent_job.status == JobStatus.RUNNING
    assert updated_recent_job.error_message is None


def test_recover_stuck_jobs_for_session_reports_zero_when_nothing_is_recovered(
    db_session,
):
    result = cli.recover_stuck_jobs_for_session(
        db=db_session,
        timeout_minutes=10,
    )

    assert result.recovered_count == 0
    assert result.recovered_job_ids == []


def test_build_parser_accepts_timeout_minutes():
    parser = cli.build_parser()

    args = parser.parse_args(["--timeout-minutes", "15"])

    assert args.timeout_minutes == 15


def test_main_prints_recovery_summary(monkeypatch, capsys):
    recorded_timeout_minutes = []

    def fake_run_recovery(timeout_minutes: int):
        recorded_timeout_minutes.append(timeout_minutes)
        return cli.RecoveryCliResult(
            recovered_count=2,
            recovered_job_ids=[10, 20],
        )

    monkeypatch.setattr(cli, "run_recovery", fake_run_recovery)
    monkeypatch.setattr(
        "sys.argv",
        ["recover_stuck_jobs.py", "--timeout-minutes", "7"],
    )

    exit_code = cli.main()

    captured = capsys.readouterr()

    assert exit_code == 0
    assert recorded_timeout_minutes == [7]
    assert "Recovered 2 stuck job(s)." in captured.out
    assert "Recovered job IDs: 10, 20" in captured.out