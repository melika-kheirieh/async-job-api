# Async Job API

A compact FastAPI + Celery backend system for handling asynchronous jobs with database-backed status tracking, worker execution, failure handling, limited retry behavior, stuck-job recovery, idempotency keys, PostgreSQL, Alembic migrations, Docker Compose, tests, and CI.

The project focuses on one practical backend problem:

> Long-running or failure-prone work should not run directly inside the request/response cycle.

Instead, the API creates a job, returns immediately, and lets a background worker process the job asynchronously while the database keeps the durable job state.

---

## What This Project Demonstrates

* API contract design for job submission
* DB-backed job status tracking
* Redis/Celery worker execution flow
* PostgreSQL-backed Docker runtime
* Alembic migration setup
* retryable vs non-retryable failure handling
* persisted failure visibility
* lifecycle metadata for debugging
* basic stuck-job recovery
* idempotency keys for duplicate job creation requests
* duplicate execution awareness through terminal-status checks
* service/repository boundaries
* API, service, and worker-processing tests
* GitHub Actions CI

This is not a full production job platform.
It is a small, explainable, production-aware backend workflow project.

---

## Tech Stack

* FastAPI
* SQLAlchemy
* PostgreSQL
* SQLite for lightweight local/test fallback
* Alembic
* Redis
* Celery
* Docker Compose
* Pytest
* GitHub Actions

---

## System Flow

```text
Client
  |
  | POST /jobs
  v
FastAPI API
  |
  | create job in DB with status=queued
  | optionally deduplicate by idempotency_key
  | enqueue Celery task with job_id
  v
Redis broker
  |
  | deliver task
  v
Celery worker
  |
  | load job from DB
  | skip if job is already terminal
  | mark job as running
  | process job
  | mark job as completed or failed, or schedule a retry
  v
PostgreSQL / database
  |
  | GET /jobs/{job_id}
  v
Client polls job status
```

Core idea:

```text
The API submits work.
The worker executes work.
The database stores the truth.
```

---

## Architecture

The project separates HTTP concerns, use-case logic, worker logic, and persistence concerns.

```text
Router  -> Service -> Repository -> Database
Worker  -> Service -> Repository -> Database
Celery task -> testable worker-processing function
```

* Router handles HTTP request/response concerns.
* Service owns job use cases and lifecycle behavior.
* Repository handles database access.
* Worker receives a `job_id`, loads the job from the database, processes it, and updates the database-backed status.

The Celery task is kept as a thin wrapper around testable worker-processing logic. This keeps worker behavior testable without requiring Redis or a running Celery worker in unit tests.

---

## Design Decisions

### Database as source of truth

The database stores durable job state:

* payload
* status
* idempotency key
* result
* error message
* attempts
* lifecycle timestamps
* creation and update timestamps

Redis is used only as the Celery broker. It is not used as the source of truth for job status or job results.

### Celery task receives only `job_id`

The Celery task receives only the job id, not the full payload.

The worker reads the job from the database. This avoids duplicating job data between the broker message and the database.

### API does not execute the job directly

The API creates the job, persists it, enqueues the background task, and returns immediately.

The actual processing happens in the worker.

### Failure is stored as state

A failed job should be visible through the API.

The worker marks failed jobs as `failed` and stores an error message in the database.

### Retry is limited and scoped

The worker distinguishes between retryable and non-retryable failures.

A logical failure should not be retried blindly. A transient failure can be retried with a limited retry count and exponential backoff.

In the current version, retry is handled by Celery retry behavior rather than a separate persisted `retrying` job status. Making retry state explicit is listed as a future improvement.

### Idempotency keys deduplicate job creation

`POST /jobs` accepts an optional `idempotency_key`.

If a client submits the same key again, the API returns the existing job instead of creating and enqueueing a duplicate job. The database enforces uniqueness for non-null idempotency keys.

This protects job creation from duplicate client requests. It is not the same thing as full exactly-once processing.

---

## Job Lifecycle

Current lifecycle paths:

```text
queued -> running -> completed
queued -> running -> failed
queued -> running -> retry scheduled by Celery -> running -> completed/failed
queued -> running -> stuck recovery -> failed
```

| Status      | Meaning                                             |
| ----------- | --------------------------------------------------- |
| `queued`    | The job was created and is waiting to be processed. |
| `running`   | The worker has started processing the job.          |
| `completed` | The job finished successfully and has a result.     |
| `failed`    | The job failed and has an error message.            |

Terminal statuses:

* `completed`
* `failed`

Once a job reaches a terminal status, the worker should not blindly process it again.

Retry is currently modeled as worker/Celery behavior, not as a separate persisted job status.

---

## API Endpoints

### Create a job

```http
POST /jobs
```

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "hello backend"}}'
```

Example response:

```json
{
  "id": 1,
  "status": "queued",
  "idempotency_key": null,
  "payload": {
    "text": "hello backend"
  },
  "result": null,
  "error_message": null,
  "attempts": 0,
  "started_at": null,
  "completed_at": null,
  "failed_at": null,
  "created_at": "2026-06-05T08:15:08.416995",
  "updated_at": "2026-06-05T08:15:08.416997"
}
```

This response means the job was created and queued. It does not mean the job has already finished.

---

### Create a job with an idempotency key

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "same request"}, "idempotency_key": "demo-123"}'
```

Send the same request again:

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "same request"}, "idempotency_key": "demo-123"}'
```

Expected behavior:

```text
the same job id is returned
a duplicate job is not created
a duplicate task is not enqueued
```

---

### Get job status

```http
GET /jobs/{job_id}
```

```bash
curl http://localhost:8001/jobs/1
```

Replace `1` with the id returned by the create-job response.

Example completed response:

```json
{
  "id": 1,
  "status": "completed",
  "idempotency_key": null,
  "payload": {
    "text": "hello backend"
  },
  "result": {
    "processed": true,
    "input_size": 25,
    "message": "Job completed successfully"
  },
  "error_message": null,
  "attempts": 1,
  "started_at": "2026-06-05T08:15:08.500101",
  "completed_at": "2026-06-05T08:15:08.526863",
  "failed_at": null,
  "created_at": "2026-06-05T08:15:08.416995",
  "updated_at": "2026-06-05T08:15:08.526863"
}
```

---

## Failure and Retry Behavior

### Non-retryable failure

A payload with `fail: true` simulates a non-retryable failure.

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "fail case", "fail": true}}'
```

Expected final status:

```text
failed
```

Expected error message:

```text
Forced failure requested by payload
```

The initial `POST /jobs` can still return successfully because it only creates and enqueues the job. The final execution outcome is observed through `GET /jobs/{job_id}`.

### Retryable failure

A payload with `transient_fail: true` simulates a retryable failure.

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "temporary problem", "transient_fail": true}}'
```

The worker treats this as retryable and schedules limited retries with exponential backoff.

In the current version, retryable failure is represented through Celery retry behavior and worker logs. It is not represented by a separate persisted `retrying` job status yet.

---

## Stuck Job Recovery

A worker can fail after marking a job as `running` but before marking it as `completed` or `failed`.

To make this failure mode visible, the service includes a simple recovery path:

* find jobs with `status = running`
* check whether `started_at` is older than a timeout threshold
* mark those jobs as `failed`
* store a clear timeout error message

Default timeout:

```text
10 minutes
```

Service method:

```python
recover_stuck_jobs(timeout_minutes=10)
```

This is intentionally basic. It does not automatically requeue jobs, run on a schedule, or implement distributed locking.

---

## Reliability Notes

Current reliability-oriented behaviors:

* database-backed status tracking
* terminal-status guard for duplicate execution awareness
* persisted failure information
* lifecycle metadata
* limited retry handling for retryable failures
* exponential backoff for retry attempts
* basic stuck-job recovery
* idempotency key support for duplicate job creation requests
* testable worker-processing logic without requiring a live broker in unit tests

Current non-guarantees:

* no explicit persisted `retrying` state yet
* no guarded job claiming with conditional DB-level transition yet
* no full exactly-once processing
* no distributed locking
* no dead-letter queue
* no automatic scheduled recovery
* no production-grade idempotency for sensitive side effects
* no full audit/event history table
* no centralized observability stack

The project is production-aware, but not a full production-grade job platform.

---

## How to Run

### Start infrastructure services

```bash
docker compose up -d postgres redis
```

### Apply migrations

```bash
docker compose run --rm api alembic upgrade head
```

### Start API and worker

```bash
docker compose up --build
```

The API will be available at:

```text
http://localhost:8001
```

The Docker Compose setup includes:

* `api`
* `worker`
* `redis`
* `postgres`

### View worker logs

```bash
docker compose logs -f worker
```

Or:

```bash
docker compose logs worker --tail=80
```

### Stop services

```bash
docker compose down
```

To remove volumes as well:

```bash
docker compose down -v
```

---

## PostgreSQL and Alembic

The default local Python runtime falls back to SQLite when `DATABASE_URL` is not set. This keeps tests and simple local runs lightweight.

The Docker Compose runtime uses PostgreSQL so the API and worker share the same database through `DATABASE_URL`.

Alembic manages database migrations.

Run migrations with:

```bash
docker compose run --rm api alembic upgrade head
```

For simple local tests, the test setup can still create the schema directly against SQLite.

---

## Running Tests

Run tests with:

```bash
pytest -q
```

The current test suite covers core API, service, and worker-processing behavior, including:

* job creation
* idempotency key behavior
* duplicate idempotency keys not enqueueing another task
* invalid request validation
* job fetching
* missing job handling
* lifecycle transitions
* stuck-job recovery
* worker success path
* non-retryable failure path
* retryable failure path
* retry countdown/backoff behavior
* terminal-status skip behavior

The core worker processing logic is tested without requiring Redis or a running Celery worker.

Full Celery/Redis integration can be validated manually through Docker Compose using the success, failure, retryable-failure, and idempotency flows shown above.

---

## CI

GitHub Actions runs the test suite on push and pull request.

The current CI workflow:

* checks out the repository
* sets up Python
* installs dependencies
* runs `pytest -q`

---

## Intentional Scope

Included in this version:

* API-based job submission
* database-backed job status tracking
* PostgreSQL Docker runtime
* Alembic migrations
* Redis/Celery worker execution
* failure visibility
* lifecycle metadata
* limited retry handling with backoff
* basic stuck-job recovery
* idempotency keys for duplicate job creation requests
* duplicate execution awareness through terminal-status checks
* API, service, and worker-processing tests
* GitHub Actions CI

Out of scope for this version:

* authentication
* frontend
* Kubernetes
* advanced monitoring
* distributed locking
* dead-letter queues
* production-grade idempotency for all side effects
* automatic scheduled recovery
* automatic requeue for stuck jobs
* multiple job types
* queue priorities
* rate limiting
* full exactly-once processing

This scope is intentional: the project focuses on the core async lifecycle and selected reliability concerns rather than trying to become a full distributed job platform.

---

## Future Improvements

The next improvements should focus on correctness and operational visibility rather than adding more infrastructure.

Planned next steps:

* guard job claiming with conditional state transitions
* make retry state explicit instead of leaving retryable jobs ambiguously `running`
* add lifecycle tests for guarded claiming and duplicate delivery
* add job listing with status filtering and pagination
* expand the Docker smoke test beyond the happy path
* improve worker logs into event-based lifecycle logs
* document design decisions and production boundaries

Possible later improvements:

* request id propagation
* metrics for queued/running/completed/failed jobs
* dead-letter queue behavior for permanently failed jobs
* carefully scoped production-grade idempotency for sensitive side effects

The next priority is not adding more tools; it is making async state transitions more defensible.

---

## Project Summary

This project is a FastAPI-based async job processing API where the API creates a job, stores it in the database, enqueues a Celery task through Redis, and returns immediately.

The worker receives only the job id, reads the job from the database, processes it, and persists the final result or failure state. PostgreSQL is the source of truth for job status, while Redis is only used as the Celery broker.

The project includes retry/failure handling, stuck-job recovery, idempotency keys for duplicate job creation, Docker Compose setup, Alembic migrations, tests, and CI.

Main trade-off:

This project is production-aware, not production-complete. It demonstrates the core async workflow and selected reliability concerns, while intentionally leaving out full exactly-once processing, distributed locking, DLQs, full observability, and production deployment hardening.
