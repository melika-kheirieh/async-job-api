import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app, get_job_service
from app.repositories import JobRepository
from app.services import JobService


@pytest.fixture()
def client():
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

    def noop_enqueue_job(job_id: int) -> None:
        return None

    def override_get_job_service():
        db = TestingSessionLocal()
        repository = JobRepository(db)
        service = JobService(
            repository=repository,
            enqueue_job=noop_enqueue_job,
        )

        try:
            yield service
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[get_job_service] = override_get_job_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_create_job_returns_queued_status(client):
    response = client.post(
        "/jobs",
        json={"payload": {"text": "hello backend"}},
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["status"] == "queued"
    assert data["payload"] == {"text": "hello backend"}
    assert data["result"] is None
    assert data["error_message"] is None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_create_job_rejects_missing_payload(client):
    response = client.post(
        "/jobs",
        json={"text": "hello backend"},
    )

    assert response.status_code == 422


def test_get_job_returns_existing_job(client):
    create_response = client.post(
        "/jobs",
        json={"payload": {"text": "hello backend"}},
    )

    job_id = create_response.json()["id"]

    get_response = client.get(f"/jobs/{job_id}")

    assert get_response.status_code == 200

    data = get_response.json()

    assert data["id"] == job_id
    assert data["status"] == "queued"
    assert data["payload"] == {"text": "hello backend"}
    assert data["result"] is None
    assert data["error_message"] is None


def test_get_missing_job_returns_404(client):
    response = client.get("/jobs/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"