# Async Job API

A small FastAPI-based async job processing project built to practice the core backend flow behind background jobs:

```text
API → Database → Redis broker → Celery worker → DB-backed job status
```

The project demonstrates job creation, asynchronous execution, worker-driven status transitions, failure handling, lightweight worker logging, and a simple duplicate execution guard.

This is a learning/interview-focused mini project, not a production-grade distributed job platform.

---

## Why This Project Exists

Long-running or failure-prone work should not run directly inside the request/response cycle.

Instead of making the client wait for processing to finish, this API:

1. creates a job in the database,
2. returns a job id immediately,
3. sends the job to a Celery worker through Redis,
4. stores the final result or error in the database,
5. lets the client poll job status through `GET /jobs/{job_id}`.

This keeps job creation separate from job execution.

---

## Tech Stack

* FastAPI — HTTP API
* SQLAlchemy — ORM and persistence layer
* SQLite — lightweight database for local learning/demo usage
* Redis — Celery broker
* Celery — background worker execution
* Docker Compose — local multi-service setup
* Pytest — basic test coverage

---

## Architecture

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
```

---

## Core Design Decisions

### Database as the source of truth

The database stores the job state:

* payload
* status
* result
* error message
* timestamps

Redis is used only as the message broker for Celery. It is not used as the source of truth for job status or results.

This makes job state persistent, queryable, and easier to debug.

---

### Celery task receives only `job_id`

The Celery task receives only the job id, not the full payload.

The worker then reads the job from the database.

This avoids duplicating job data between the broker message and the database, and keeps the database as the single source of truth.

---

### Service and repository boundaries

The project keeps HTTP, use-case logic, and persistence concerns separated:

```text
Router → Service → Repository → Database
Worker → Service → Repository → Database
```

* Router handles HTTP request/response concerns.
* Service owns job lifecycle operations.
* Repository handles database access.
* Worker uses the service layer instead of embedding persistence logic directly.

---

## Job Lifecycle

A job can move through these states:

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

The terminal statuses are:

* `completed`
* `failed`

Once a job is in a terminal status, the worker should not blindly process it again.

---

## API Endpoints

### Create a job

```http
POST /jobs
```

Example:

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

The response means the job was created and queued. It does not mean processing has already finished.

---

### Get a job

```http
GET /jobs/{job_id}
```

Example:

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

Example:

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

The initial `POST /jobs` can still return successfully because it only creates and enqueues the job. The final execution outcome is observed through `GET /jobs/{job_id}`.

---

## Worker Logging

The worker logs key execution events:

* job processing started
* job completed
* job failed
* terminal job skipped

Example logs:

```text
Starting job processing: job_id=8
Job completed: job_id=8
Starting job processing: job_id=9
Job failed: job_id=9 error=Forced failure requested by payload
```

This is intentionally lightweight logging, not a full observability setup.

---

## Duplicate Execution Guard

Broker-based systems may deliver or execute a task more than once.

To avoid blindly re-processing finished jobs, the worker checks whether a job is already in a terminal status before processing it:

* `completed`
* `failed`

This is a simplified duplicate execution guard. It is useful for this mini project, but it is not full production-grade idempotency.

---

## Limitations

This project intentionally does not implement:

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

For sensitive side effects such as payments, emails, notifications, or external API calls, a stronger design would be required.

Examples of stronger production-oriented patterns include:

* idempotency keys
* unique transaction records
* outbox-like patterns
* retry policies with backoff
* stuck job cleanup or reconciliation
* structured logging with `job_id` / `request_id`
* stronger transaction boundaries around side effects

---

## SQLite Note

This project uses SQLite for simplicity.

SQLite is acceptable for a small local learning project, but it is not the best choice for a production-like multi-process worker/API setup.

For a more realistic backend setup, PostgreSQL would be preferred because it handles concurrent access, transactions, constraints, and production workloads more robustly.

---

## How to Run

### Start services

```bash
docker compose up --build
```

The API is available at:

```text
http://localhost:8001
```

The Docker Compose setup includes:

* `api`
* `worker`
* `redis`

The API container listens internally on port `8000` and is mapped to port `8001` on the host.

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

Poll the job:

```bash
curl http://localhost:8001/jobs/1
```

Expected final status:

```text
completed
```

---

### Failing job

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

Expected final status:

```text
failed
```

Expected error message:

```text
Forced failure requested by payload
```

---

## Running Tests

Run tests with:

```bash
pytest
```

The test suite covers the core API and job lifecycle behavior, including:

* creating a job
* fetching an existing job
* handling missing jobs
* job lifecycle transitions
* completed jobs
* failed jobs

---

## Design Summary

This project demonstrates a small but realistic async job processing flow.

The FastAPI API creates a job in the database with `queued` status and enqueues a Celery task through Redis. The worker receives only the `job_id`, reads the job from the database, marks it as `running`, performs simplified processing, and then marks it as `completed` or `failed`.

The database is the source of truth for job status, result, and error information. Redis is used only as the broker.

The project also includes a simple failure path, lightweight worker logging, and a terminal-status guard to avoid blindly re-processing jobs that are already completed or failed.

This is not full production-grade idempotency, but it shows the reliability concerns and where stronger patterns would be needed.

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
* add structured logging with `job_id` / `request_id`
* add CI
* add integration tests for worker behavior
* add metrics for queued/running/completed/failed jobs

---

## Repository Status

This is a learning/interview-focused backend mini project.

The goal is not to build a complete production job platform. The goal is to demonstrate understanding of async job processing, worker execution, DB-backed state tracking, failure handling, and reliability trade-offs.
