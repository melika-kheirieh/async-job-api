# Async Job API

A compact FastAPI + Celery backend system for handling asynchronous jobs with database-backed status tracking, worker execution, failure handling, limited retry handling, stuck-job recovery, idempotency keys, PostgreSQL, Alembic migrations, Docker Compose, tests, and CI.

The project focuses on one practical backend problem:

> Long-running or failure-prone work should not run directly inside the request/response cycle.

Instead, the API creates a job, returns immediately, and lets a background worker process the job asynchronously while the database keeps the durable job state.

---

## What This Project Demonstrates

This project demonstrates a small but realistic async backend workflow:

- API contract design for job submission
- DB-backed job status tracking
- Redis/Celery worker execution flow
- PostgreSQL-backed Docker runtime
- Alembic migration setup
- retryable vs non-retryable failure handling
- persisted failure visibility
- lifecycle metadata for debugging
- basic stuck-job recovery
- idempotency keys for duplicate job creation requests
- duplicate execution awareness through terminal-status checks
- service/repository boundaries
- API, service, and worker-processing tests
- GitHub Actions CI

The goal is not to build a full production job platform.  
The goal is to show a clean, explainable, production-aware backend workflow.

---

## Tech Stack

- FastAPI — HTTP API
- SQLAlchemy — ORM and persistence layer
- PostgreSQL — Docker Compose database runtime
- SQLite — lightweight local/test fallback
- Alembic — database migrations
- Redis — Celery broker
- Celery — background task execution and retry handling
- Docker Compose — local multi-service setup
- Pytest — API, service, and worker-processing tests
- GitHub Actions — automated test runs

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

### Router

The router handles HTTP request and response concerns.  
It receives API input, delegates use cases to the service layer, and returns response models.

### Service

The service owns the job use cases.  
It creates jobs, reads jobs, handles job creation idempotency, applies lifecycle transitions, and exposes basic stuck-job recovery.

### Repository

The repository handles database access.  
It creates job records, loads jobs by id or idempotency key, finds stuck running jobs, and persists status, result, error information, attempts, idempotency keys, and lifecycle timestamps.

### Worker

The worker receives a `job_id`, loads the job through the service/repository path, processes the job, and updates the database-backed status.

The Celery task is kept as a thin wrapper around testable worker-processing logic.  
This keeps worker behavior testable without requiring Redis or a running Celery worker in unit tests.

---

## Core Design Decisions

### Database as the source of truth

The database stores durable job state:

- payload
- status
- idempotency key
- result
- error message
- attempts
- lifecycle timestamps
- creation and update timestamps

Redis is used only as the Celery message broker.  
It is not used as the source of truth for job status or job results.

This keeps job state persistent, queryable, and easier to debug.

### Celery task receives only `job_id`

The Celery task receives only the job id, not the full payload.

The worker then reads the job from the database.  
This avoids duplicating job data between the broker message and the database, and keeps the database as the single source of truth.

### API does not execute the job directly

The API should stay responsive.

It creates the job, persists it, enqueues the background task, and returns immediately.  
The actual processing happens in the worker.

### Failure is stored as state

A failed job should be visible through the API.

Instead of treating failure as only a worker-side crash or log message, the worker marks the job as `failed` and stores an error message in the database.

### Retry is limited and scoped

The worker distinguishes between retryable and non-retryable failures.

A logical failure should not be retried blindly.  
A transient failure can be retried with a limited retry count and exponential backoff.

In the current version, retry is handled by Celery retry behavior rather than a separate persisted `retrying` job status. Making retry state explicit is intentionally listed as a future improvement.

### Stuck jobs are made visible

A worker may crash after marking a job as `running` but before marking it as `completed` or `failed`.

To avoid leaving such jobs in `running` forever, the service includes a basic stuck-job recovery path. Jobs that remain `running` longer than a timeout threshold can be marked as `failed` with a clear timeout error message.

This is intentionally a simple recovery mechanism, not a full scheduler or requeue system.

### Idempotency keys deduplicate job creation

`POST /jobs` accepts an optional `idempotency_key`.

If a client submits the same key again, the API returns the existing job instead of creating and enqueueing a duplicate job. The database enforces uniqueness for non-null idempotency keys.

This protects job creation from duplicate client requests.

It is not the same thing as full exactly-once processing.

### Duplicate execution awareness

Broker-based systems may deliver or execute a task more than once.

This project includes a simplified terminal-status guard: if a job is already `completed` or `failed`, the worker skips it instead of blindly processing it again.

This is not full production-grade idempotency, but it shows where the duplicate-execution risk exists.

---

## Job Lifecycle

Current lifecycle paths:

```text
queued -> running -> completed
queued -> running -> failed
queued -> running -> retry scheduled by Celery -> running -> completed/failed
queued -> running -> stuck recovery -> failed
```

| Status | Meaning |
| --- | --- |
| `queued` | The job was created and is waiting to be processed. |
| `running` | The worker has started processing the job. |
| `completed` | The job finished successfully and has a result. |
| `failed` | The job failed and has an error message. |

Terminal statuses:

- `completed`
- `failed`

Once a job reaches a terminal status, the worker should not blindly process it again.

Retry is currently modeled as worker/Celery behavior, not as a separate persisted job status. A future improvement is to add an explicit `retrying` status so the API state reflects retry backoff more precisely.

---

## Job Metadata

Each job stores lightweight lifecycle metadata:

| Field | Meaning |
| --- | --- |
| `idempotency_key` | Optional client-provided key used to deduplicate job creation requests. |
| `attempts` | Number of times the worker started processing the job. |
| `started_at` | Timestamp for when the worker started the latest processing attempt. |
| `completed_at` | Timestamp for successful completion. |
| `failed_at` | Timestamp for failure. |
| `created_at` | Timestamp for job creation. |
| `updated_at` | Timestamp for the latest update. |

This metadata is intentionally lightweight.  
It is not a full audit log or job history table.

---

## API Endpoints

### Create a job

```http
POST /jobs
```

Example request:

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

This response means the job was created and queued.  
It does not mean the job has already finished.

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

This is request deduplication for job creation.  
It is not a full exactly-once guarantee for all possible side effects.

---

### Get job status

```http
GET /jobs/{job_id}
```

Example request:

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

## Failure Handling

### Non-retryable failure

A payload with `fail: true` simulates a non-retryable failure.

In this case, the worker marks the job as `failed` immediately because retrying the same logical failure would not change the outcome.

Example request:

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

The initial `POST /jobs` can still return successfully because it only creates and enqueues the job.  
The final execution outcome is observed through `GET /jobs/{job_id}`.

---

### Retryable failure

A payload with `transient_fail: true` simulates a retryable failure.

In this case, the Celery task schedules limited retries with exponential backoff.

Example request:

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "temporary problem", "transient_fail": true}}'
```

This models temporary failures such as:

- short-lived network issues
- external service timeouts
- temporary infrastructure problems

In the current version, retryable failure is represented through Celery retry behavior and worker logs. It is not represented by a separate persisted `retrying` job status yet.

The retry behavior is intentionally limited.  
The project does not claim production-grade retry orchestration, dead-letter queues, or exactly-once execution.

---

## Stuck Job Recovery

A worker can fail after marking a job as `running` but before marking it as `completed` or `failed`.

In that case, the job may remain stuck in the `running` state forever.

To make this failure mode visible, the service includes a simple recovery path:

- find jobs with `status = running`
- check whether `started_at` is older than a timeout threshold
- mark those jobs as `failed`
- store a clear timeout error message

Default timeout:

```text
10 minutes
```

Service method:

```python
recover_stuck_jobs(timeout_minutes=10)
```

This is intentionally a basic recovery mechanism.  
It does not automatically requeue jobs, run on a schedule, or implement distributed locking.

In a production system, this kind of recovery would typically be executed by a scheduled reconciliation job and would need stronger concurrency controls.

---

## Worker Logging

The worker logs key execution events:

- job processing started
- job completed
- job failed
- retryable failure detected
- retry scheduled
- job failed after retry limit
- terminal job skipped
- missing job skipped

Example logs:

```text
Starting job processing: job_id=8
Job completed: job_id=8
Starting job processing: job_id=9
Job failed with non-retryable error: job_id=9 error=Forced failure requested by payload
Starting job processing: job_id=10
Job failed with retryable error: job_id=10
Retrying job: job_id=10 retry=1 countdown=1 error=Transient failure requested by payload
Skipping terminal job: job_id=11 status=completed
```

This is intentionally lightweight logging, not a full observability setup.

For a production system, this could be extended with request id propagation, centralized structured logging, tracing, metrics, and alerting.

---

## Reliability Notes

This project intentionally separates durable state from message delivery:

- The database stores job state, payload, result, error information, attempts, idempotency keys, and lifecycle timestamps.
- Redis delivers task messages to Celery workers.
- The worker updates job state in the database as processing progresses.

This means the database is the best place to inspect the current job state.

Current reliability-oriented behaviors:

- database-backed status tracking
- terminal-status guard for duplicate execution awareness
- persisted failure information
- lifecycle metadata
- limited retry handling for retryable failures
- exponential backoff for retry attempts
- basic stuck-job recovery
- idempotency key support for duplicate job creation requests
- testable worker-processing logic without requiring a live broker in unit tests

Current non-guarantees:

- no explicit persisted `retrying` state yet
- no guarded job claiming with conditional DB-level transition yet
- no full exactly-once processing
- no distributed locking
- no dead-letter queue
- no automatic scheduled recovery
- no production-grade idempotency for sensitive side effects
- no full audit/event history table
- no centralized observability stack

The project is production-aware, but not a full production-grade job platform.

---

## PostgreSQL Docker Runtime

The default local Python runtime falls back to SQLite when `DATABASE_URL` is not set.  
This keeps tests and simple local runs lightweight.

The Docker Compose runtime uses PostgreSQL so the API and worker share the same database through `DATABASE_URL`.

PostgreSQL stores data in the named Docker volume:

```text
pg_data
```

Use this command when you want to remove local database state:

```bash
docker compose down -v
```

Warning: removing volumes may delete local database state.

---

## Alembic Migrations

This project includes Alembic for database migration management.

In the Docker Compose runtime, the database schema should be created or updated through Alembic migrations instead of relying on application startup to create tables implicitly.

Run migrations with:

```bash
docker compose run --rm api alembic upgrade head
```

For simple local tests, the test setup can still create the schema directly against SQLite.

This split is intentional:

- Alembic is used for versioned database schema changes.
- SQLite test setup stays lightweight and fast.

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

- `api`
- `worker`
- `redis`
- `postgres`

The API container listens internally on port `8000` and is mapped to port `8001` on the host.

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

## Example Flow

### Successful job

Create a job:

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "hello service boundary"}}'
```

The response contains an `id`.

Poll the job:

```bash
curl http://localhost:8001/jobs/1
```

Replace `1` with the id returned by the create-job response.

Expected final status:

```text
completed
```

---

### Non-retryable failing job

Create a job that intentionally fails during worker processing:

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "fail case", "fail": true}}'
```

Poll the job:

```bash
curl http://localhost:8001/jobs/2
```

Replace `2` with the id returned by the create-job response.

Expected final status:

```text
failed
```

Expected error message:

```text
Forced failure requested by payload
```

---

### Retryable failing job

Create a job that simulates a transient failure:

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "temporary problem", "transient_fail": true}}'
```

Inspect worker logs:

```bash
docker compose logs worker --tail=80
```

The worker treats this as retryable and schedules limited retries with exponential backoff.

---

### Idempotent job creation

Create a job with an idempotency key:

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

## Running Tests

Run tests with:

```bash
pytest -q
```

The current test suite covers core API, service, and worker-processing behavior, including:

- creating a job
- creating a job with an idempotency key
- returning an existing job for a duplicate idempotency key
- ensuring duplicate idempotency keys do not enqueue another task
- creating separate jobs when no idempotency key is provided
- rejecting invalid job creation requests
- fetching an existing job
- returning 404 for unknown jobs
- initial queued status
- running transition
- completed transition
- failed transition
- missing-job service errors
- enqueue boundary behavior without requiring a real broker
- stuck-job recovery for old running jobs
- stuck-job recovery leaving recent running jobs untouched
- stuck-job recovery leaving terminal jobs untouched
- worker processing success path
- worker processing non-retryable failure path
- worker processing retryable failure path
- retry countdown/backoff behavior
- terminal-status skip behavior

The core worker processing logic is tested without requiring Redis or a running Celery worker.

Full Celery/Redis integration can be validated manually through Docker Compose using the success, failure, retryable-failure, and idempotency flows shown above.

---

## CI

GitHub Actions runs the test suite on push and pull request.

The current CI workflow:

- checks out the repository
- sets up Python
- installs dependencies
- runs `pytest -q`

---

## Dependency Downloads

The Docker build installs Python packages using Liara's PyPI mirror as the primary index and `pypi.org` as a fallback.

If needed, rebuild Docker images with:

```bash
docker compose build --no-cache api worker
```

The `wheels/` directory is ignored by git and should remain local only.

---

## Intentional Scope

This project intentionally focuses on a compact async job-processing flow rather than full production infrastructure.

Included in this version:

- API-based job submission
- database-backed job status tracking
- PostgreSQL Docker runtime
- Alembic migrations
- Redis/Celery worker execution
- failure visibility
- lifecycle metadata
- limited retry handling with backoff
- basic stuck-job recovery
- idempotency keys for duplicate job creation requests
- duplicate execution awareness through terminal-status checks
- API, service, and worker-processing tests
- GitHub Actions CI

Out of scope for this version:

- authentication
- frontend
- Kubernetes
- advanced monitoring
- distributed locking
- dead-letter queues
- production-grade idempotency for all side effects
- automatic scheduled recovery
- automatic requeue for stuck jobs
- multiple job types
- queue priorities
- rate limiting
- full exactly-once processing

This scope is intentional: the project focuses on the core async lifecycle and selected reliability concerns rather than trying to become a full distributed job platform.

---

## Future Improvements

The next improvements should focus on correctness and operational visibility rather than adding more infrastructure.

Planned or possible next steps:

- guard job claiming with conditional state transitions
- make retry state explicit instead of leaving retryable jobs ambiguously `running`
- add lifecycle tests for guarded claiming and duplicate delivery
- add job listing with status filtering and pagination
- expand the Docker smoke test beyond the happy path
- improve worker logs into event-based lifecycle logs
- document design decisions and production boundaries
- add request id propagation
- add metrics for queued/running/completed/failed jobs
- add dead-letter queue behavior for permanently failed jobs
- add carefully scoped production-grade idempotency for sensitive side effects

These are intentionally incremental improvements.  
The next priority is not adding more tools; it is making async state transitions more defensible.

---

## Project Summary

This project is a FastAPI-based async job processing API where the API creates a job, stores it in the database, enqueues a Celery task through Redis, and returns immediately.

The worker receives only the job id, reads the job from the database, processes it, and persists the final result or failure state. PostgreSQL is the source of truth for job status, while Redis is only used as the Celery broker.

The project includes retry/failure handling, stuck-job recovery, idempotency keys for duplicate job creation, Docker Compose setup, Alembic migrations, tests, and CI.

Main trade-off:

This project is production-aware, not production-complete. It demonstrates the core async workflow and selected reliability concerns, while intentionally leaving out full exactly-once processing, distributed locking, DLQs, full observability, and production deployment hardening.