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
def testing_session_local():
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

    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


@pytest.fixture()
def client(testing_session_local):
    def noop_enqueue_job(job_id: int) -> None:
        return None

    def override_get_job_service():
        db = testing_session_local()
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


@pytest.fixture()
def job_repository(testing_session_local):
    db = testing_session_local()
    repository = JobRepository(db)

    try:
        yield repository
    finally:
        db.close()


def create_job(client, payload=None, idempotency_key=None):
    request_body = {
        "payload": payload or {"text": "hello backend"},
    }

    if idempotency_key is not None:
        request_body["idempotency_key"] = idempotency_key

    return client.post(
        "/jobs",
        json=request_body,
    )


def test_create_job_returns_queued_status(client):
    response = create_job(
        client,
        payload={"text": "hello backend"},
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["status"] == "queued"
    assert data["idempotency_key"] is None
    assert data["payload"] == {"text": "hello backend"}
    assert data["result"] is None
    assert data["error_message"] is None
    assert data["attempts"] == 0
    assert data["started_at"] is None
    assert data["completed_at"] is None
    assert data["failed_at"] is None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_create_job_with_idempotency_key_returns_key(client):
    response = create_job(
        client,
        payload={"text": "hello backend"},
        idempotency_key="request-123",
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["status"] == "queued"
    assert data["idempotency_key"] == "request-123"
    assert data["payload"] == {"text": "hello backend"}
    assert data["result"] is None
    assert data["error_message"] is None
    assert data["attempts"] == 0
    assert data["started_at"] is None
    assert data["completed_at"] is None
    assert data["failed_at"] is None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_create_job_with_duplicate_idempotency_key_returns_existing_job(client):
    first_response = create_job(
        client,
        payload={"text": "hello backend"},
        idempotency_key="request-123",
    )
    second_response = create_job(
        client,
        payload={"text": "hello backend"},
        idempotency_key="request-123",
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    first_data = first_response.json()
    second_data = second_response.json()

    assert second_data["id"] == first_data["id"]
    assert second_data["status"] == "queued"
    assert second_data["idempotency_key"] == "request-123"
    assert second_data["payload"] == {"text": "hello backend"}


def test_create_job_without_idempotency_key_creates_separate_jobs(client):
    first_response = create_job(
        client,
        payload={"text": "hello backend"},
    )
    second_response = create_job(
        client,
        payload={"text": "hello backend"},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    first_data = first_response.json()
    second_data = second_response.json()

    assert second_data["id"] != first_data["id"]
    assert first_data["idempotency_key"] is None
    assert second_data["idempotency_key"] is None


def test_create_job_rejects_missing_payload(client):
    response = client.post(
        "/jobs",
        json={"text": "hello backend"},
    )

    assert response.status_code == 422


def test_create_job_rejects_empty_idempotency_key(client):
    response = client.post(
        "/jobs",
        json={
            "payload": {"text": "hello backend"},
            "idempotency_key": "",
        },
    )

    assert response.status_code == 422


def test_get_job_returns_existing_job(client):
    create_response = create_job(
        client,
        payload={"text": "hello backend"},
    )
    job_id = create_response.json()["id"]

    get_response = client.get(f"/jobs/{job_id}")

    assert get_response.status_code == 200

    data = get_response.json()

    assert data["id"] == job_id
    assert data["status"] == "queued"
    assert data["idempotency_key"] is None
    assert data["payload"] == {"text": "hello backend"}
    assert data["result"] is None
    assert data["error_message"] is None
    assert data["attempts"] == 0
    assert data["started_at"] is None
    assert data["completed_at"] is None
    assert data["failed_at"] is None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_get_missing_job_returns_404(client):
    response = client.get("/jobs/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_list_jobs_returns_all_jobs_ordered_by_newest_first(client):
    first_response = create_job(
        client,
        payload={"text": "first job"},
    )
    second_response = create_job(
        client,
        payload={"text": "second job"},
    )

    response = client.get("/jobs")

    assert response.status_code == 200

    data = response.json()

    assert data["limit"] == 20
    assert data["offset"] == 0
    assert data["count"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["id"] == second_response.json()["id"]
    assert data["items"][1]["id"] == first_response.json()["id"]


def test_list_jobs_filters_by_status(client, job_repository):
    queued_response = create_job(
        client,
        payload={"text": "queued job"},
    )
    failed_response = create_job(
        client,
        payload={"text": "failed job"},
    )

    queued_job_id = queued_response.json()["id"]
    failed_job_id = failed_response.json()["id"]

    job_repository.mark_failed(
        job_id=failed_job_id,
        error_message="Forced failure for test",
    )

    response = client.get("/jobs?status=failed")

    assert response.status_code == 200

    data = response.json()

    assert data["count"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == failed_job_id
    assert data["items"][0]["id"] != queued_job_id
    assert data["items"][0]["status"] == "failed"
    assert data["items"][0]["error_message"] == "Forced failure for test"


def test_list_jobs_filters_by_retrying_status(client, job_repository):
    response = create_job(
        client,
        payload={"text": "retrying job"},
    )

    job_id = response.json()["id"]

    job_repository.mark_retrying(
        job_id=job_id,
        error_message="Temporary failure for test",
    )

    list_response = client.get("/jobs?status=retrying")

    assert list_response.status_code == 200

    data = list_response.json()

    assert data["count"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == job_id
    assert data["items"][0]["status"] == "retrying"
    assert data["items"][0]["error_message"] == "Temporary failure for test"


def test_list_jobs_supports_limit_and_offset(client):
    first_response = create_job(
        client,
        payload={"text": "first job"},
    )
    second_response = create_job(
        client,
        payload={"text": "second job"},
    )
    third_response = create_job(
        client,
        payload={"text": "third job"},
    )

    response = client.get("/jobs?limit=1&offset=1")

    assert response.status_code == 200

    data = response.json()

    assert data["limit"] == 1
    assert data["offset"] == 1
    assert data["count"] == 3
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == second_response.json()["id"]
    assert data["items"][0]["id"] != first_response.json()["id"]
    assert data["items"][0]["id"] != third_response.json()["id"]


def test_list_jobs_rejects_invalid_status(client):
    response = client.get("/jobs?status=unknown")

    assert response.status_code == 422


def test_list_jobs_rejects_invalid_limit(client):
    response = client.get("/jobs?limit=0")

    assert response.status_code == 422


def test_list_jobs_rejects_invalid_offset(client):
    response = client.get("/jobs?offset=-1")

    assert response.status_code == 422