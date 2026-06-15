## Overview

Long-running or failure-prone work should not run directly inside the request/response cycle.

Instead of making the client wait for processing to finish, this API:

1. creates a job record in the database,
2. returns a job id immediately,
3. enqueues a Celery task through Redis,
4. lets a worker process the job asynchronously,
5. stores the final result or error in the database,
6. allows the client to poll job status through `GET /jobs/{job_id}`.

The main idea is simple:

> The API submits work.  
> The worker executes work.  
> The database stores the truth.

---

## What This Project Demonstrates

This project focuses on the core backend workflow behind asynchronous job processing:

- API contract design for job submission
- database-backed job status tracking
- Redis/Celery worker execution flow
- worker-driven job lifecycle transitions
- failure visibility through persisted state
- duplicate execution awareness
- service/repository boundaries
- Docker Compose based local setup
- API, service, and worker-processing tests
- CI with GitHub Actions

The goal is not to build a full production job platform.

The goal is to show a clean, explainable backend workflow for submitting, processing, tracking, and debugging background jobs.

---

## Tech Stack

- FastAPI — HTTP API
- SQLAlchemy — ORM and persistence layer
- SQLite — lightweight local database
- Redis — Celery broker
- Celery — background worker execution
- Docker Compose — local multi-service setup
- Pytest — API, service, and worker-processing tests
- GitHub Actions — test automation

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
  | enqueue Celery task with job_id
  v
Redis broker
  |
  | deliver task
  v
Celery worker
  |
  | read job from DB
  | mark job as running
  | process job
  | mark job as completed or failed
  v
Database
  |
  | GET /jobs/{job_id}
  v
Client polls job status
````

---

## Architecture

The project keeps HTTP concerns, use-case logic, and persistence concerns separated:

```text
Router  → Service → Repository → Database
Worker  → Service → Repository → Database
```

### Router

The router handles HTTP request and response concerns.

It receives API input, delegates the use case to the service layer, and returns a response model.

### Service

The service owns job lifecycle operations.

It creates jobs, reads jobs, and applies state transitions such as:

* `queued`
* `running`
* `completed`
* `failed`

### Repository

The repository handles database access.

It creates job records, loads jobs by id, and persists status/result/error updates.

### Worker

The worker receives a `job_id`, loads the job through the service/repository path, processes the job, and updates the database-backed status.

The Celery task is kept as a thin wrapper around testable worker-processing logic.

---

## Core Design Decisions

### Database as the source of truth

The database stores the durable job state:

* payload
* status
* result
* error message
* timestamps

Redis is used only as the Celery message broker.

It is not used as the source of truth for job status or job results. This keeps job state persistent, queryable, and easier to debug.

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

### Duplicate execution awareness

Broker-based systems may deliver or execute a task more than once.

This project includes a simplified terminal-status guard: if a job is already `completed` or `failed`, the worker should not blindly process it again.

This is not full production-grade idempotency, but it shows where the duplicate-execution risk exists.

---

## Job Lifecycle

A job can move through one of these flows:

```text
queued → running → completed
queued → running → failed
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
  "payload": {
    "text": "hello backend"
  },
  "result": null,
  "error_message": null,
  "created_at": "2026-06-05T08:15:08.416995",
  "updated_at": "2026-06-05T08:15:08.416997"
}
```

This response means the job was created and queued.

It does not mean the job has already finished.

---

### Get job status

```http
GET /jobs/{job_id}
```

Example request:

```bash
curl http://localhost:8001/jobs/1
```

Example completed response:

```json
{
  "id": 1,
  "status": "completed",
  "payload": {
    "text": "hello backend"
  },
  "result": {
    "processed": true,
    "input_size": 25,
    "message": "Job completed successfully"
  },
  "error_message": null,
  "created_at": "2026-06-05T08:15:08.416995",
  "updated_at": "2026-06-05T08:15:08.526863"
}
```

---

## Failure Handling

The project includes a simple worker failure path.

If the job payload contains `fail: true`, the worker intentionally raises an internal processing error, marks the job as `failed`, and stores the error message in the database.

Example request:

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "fail case", "fail": true}}'
```

Example failed response from `GET /jobs/{job_id}`:

```json
{
  "id": 2,
  "status": "failed",
  "payload": {
    "text": "fail case",
    "fail": true
  },
  "result": null,
  "error_message": "Forced failure requested by payload",
  "created_at": "2026-06-05T08:15:20.984801",
  "updated_at": "2026-06-05T08:15:20.994819"
}
```

The initial `POST /jobs` can still return successfully because it only creates and enqueues the job.

The final execution outcome is observed through `GET /jobs/{job_id}`.

---

## Worker Logging

The worker logs key execution events:

* job processing started
* job completed
* job failed
* terminal job skipped
* missing job skipped

Example logs:

```text
Starting job processing: job_id=8
Job completed: job_id=8

Starting job processing: job_id=9
Job failed: job_id=9 error=Forced failure requested by payload

Skipping terminal job: job_id=10 status=completed
```

This is intentionally lightweight logging, not a full observability setup.

For a production system, this could be extended with request id propagation, centralized structured logging, tracing, metrics, and alerting.

---

## Duplicate Execution Guard

Broker-based systems may deliver or execute a task more than once.

To avoid blindly re-processing finished jobs, the worker checks whether a job is already in a terminal status before processing it:

* `completed`
* `failed`

This is a simplified duplicate execution guard.

For sensitive side effects such as payments, emails, notifications, or external API calls, checking terminal job status alone would not be enough.

Those cases require stronger idempotency guarantees, such as:

* idempotency keys
* unique transaction records
* outbox-like patterns
* stronger transaction boundaries around side effects

---

## Reliability Notes

This project intentionally separates durable state from message delivery:

* The database stores job state, payload, result, and error information.
* Redis delivers task messages to Celery workers.
* The worker updates job state in the database as processing progresses.

This means the database is the best place to inspect the current job state.

However, this project does not fully solve all distributed job-processing failure modes.

For example:

* a worker may crash while processing a job,
* a broker may redeliver a task,
* a task may run more than once,
* a job may remain stuck in `running`,
* retries may need backoff and retry-count tracking.

The project includes a small terminal-status guard, but production systems need stronger reliability patterns.

---

## PostgreSQL Docker Runtime

The default local Python runtime still falls back to SQLite when `DATABASE_URL` is not set, which keeps tests and simple local runs lightweight.

The Docker Compose runtime uses PostgreSQL so the API and worker share the same database through `DATABASE_URL`.

---

## How to Run

### Start services

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

The API container listens internally on port `8000` and is mapped to port `8001` on the host.

PostgreSQL stores data in the named Docker volume `pg_data`. Use `docker compose down -v` when you want to remove that local database state.

### Dependency downloads

The Docker build installs Python packages with Liara's PyPI mirror as the primary index and `pypi.org` as a fallback:

```bash
docker compose build --no-cache api worker
```

If local network conditions still make direct package downloads unreliable, create a temporary wheelhouse from a Linux Python 3.12 container and build with an offline Dockerfile edit that installs from `/wheels`:

```bash
mkdir -p wheels
docker run --rm -v "$PWD:/src" -w /src python:3.12-slim \
  python -m pip download --dest wheels --prefer-binary \
  --retries 10 --timeout 120 \
  --index-url https://package-mirror.liara.ir/repository/pypi/simple \
  --extra-index-url https://pypi.org/simple \
  -r requirements.txt
```

The `wheels/` directory is ignored by git and should remain local only.

---

### View worker logs

```bash
docker compose logs -f worker
```

Or:

```bash
docker compose logs worker --tail=80
```

---

### Stop services

```bash
docker compose down
```

To remove volumes as well:

```bash
docker compose down -v
```

Warning: removing volumes may delete local database state.

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

Use that id when polling the job:

```bash
curl http://localhost:8001/jobs/<JOB_ID>
```

Expected final status:

```text
completed
```

Example final response:

```json
{
  "id": 10,
  "status": "completed",
  "payload": {
    "text": "hello service boundary"
  },
  "result": {
    "processed": true,
    "input_size": 33,
    "message": "Job completed successfully"
  },
  "error_message": null,
  "created_at": "2026-06-05T08:37:41.235786",
  "updated_at": "2026-06-05T08:37:41.337479"
}
```

---

### Failing job

Create a job that intentionally fails during worker processing:

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "fail case", "fail": true}}'
```

The response contains an `id`.

Poll the job:

```bash
curl http://localhost:8001/jobs/<JOB_ID>
```

Expected final status:

```text
failed
```

Expected error message:

```text
Forced failure requested by payload
```

Example final response:

```json
{
  "id": 11,
  "status": "failed",
  "payload": {
    "text": "fail case",
    "fail": true
  },
  "result": null,
  "error_message": "Forced failure requested by payload",
  "created_at": "2026-06-05T08:37:46.674055",
  "updated_at": "2026-06-05T08:37:46.684110"
}
```

---

## Running Tests

Run tests with:

```bash
pytest -q
```

The current test suite covers core API, service, and worker-processing behavior, including:

* creating a job
* rejecting invalid job creation requests
* fetching an existing job
* returning 404 for unknown jobs
* initial queued status
* running transition
* completed transition
* failed transition
* missing-job service errors
* enqueue boundary behavior without requiring a real broker
* worker processing success path
* worker processing failure path
* terminal-status skip behavior

The core worker processing logic is tested without requiring Redis or a running Celery worker.

Full Celery/Redis integration is validated manually through Docker Compose using the success and failure flows shown above.

---

## CI

GitHub Actions runs the test suite on push and pull request.

The current CI workflow:

* checks out the repository,
* sets up Python,
* installs dependencies,
* runs `pytest -q`.

---

## Intentional Scope

This project intentionally focuses on a compact async job-processing flow rather than full production infrastructure.

Out of scope for this version:

* authentication
* frontend
* Alembic migrations
* PostgreSQL migration
* Kubernetes
* advanced monitoring
* distributed locking
* production-grade retries
* production-grade idempotency
* stuck job recovery
* multiple job types
* queue priorities
* rate limiting

This scope is intentional: the project focuses on the core async lifecycle rather than trying to become a full distributed job platform.

---

## Future Improvements

Possible next steps:

* migrate from SQLite to PostgreSQL
* add Alembic migrations
* add retry policy with backoff
* add retry count and retry status tracking
* add stuck job cleanup or reconciliation
* add idempotency keys
* add stronger side-effect protection
* add request id propagation and centralized structured logging
* add linting and formatting checks to CI
* add Celery/Redis integration tests
* add metrics for queued/running/completed/failed jobs

---

## Design Summary

This project demonstrates a small but realistic async job-processing flow.

The FastAPI API creates a job in the database with `queued` status and enqueues a Celery task through Redis.

The worker receives only the `job_id`, reads the job from the database, marks it as `running`, performs simplified processing, and then marks it as `completed` or `failed`.

The database is the source of truth for job status, result, and error information.

Redis is used only as the broker.

The project also includes a simple failure path, lightweight worker logging, a testable worker-processing function, CI, and a terminal-status guard to avoid blindly re-processing jobs that are already completed or failed.

This is not full production-grade idempotency, but it shows the reliability concerns and where stronger patterns would be needed.
