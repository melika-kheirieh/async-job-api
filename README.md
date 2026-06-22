# Async Job API

A compact FastAPI and Celery backend that makes asynchronous job state explicit,
durable, and testable.

The API persists work and returns immediately. Celery processes it in the
background, Redis coordinates delivery, and PostgreSQL remains the source of
truth for the job lifecycle.

> This project is production-aware, not production-complete. It handles selected
> retry, duplicate-delivery, and recovery risks without claiming exactly-once
> execution or exactly-once side effects.

## Reliability Model

| Concern | Current approach |
|---|---|
| Durable job state | PostgreSQL stores status, payload, result, errors, attempts, and timestamps. |
| Task delivery | Redis is used only as the Celery broker. |
| Concurrent delivery | A conditional database update allows only one successful claim. |
| Retry visibility | Retryable failures persist an explicit `retrying` state. |
| Duplicate submission | A unique idempotency key returns the existing job. |
| Stuck execution | Manual recovery fails old `running` jobs conditionally. |
| Operational visibility | Stable lifecycle events include `job_id` and execution context. |
| Exactly-once behavior | Not guaranteed; side-effecting handlers must be idempotent. |

## Architecture

```mermaid
flowchart LR
    Client["Client"] --> API["FastAPI"]
    API --> DB["PostgreSQL"]
    API --> Redis["Redis broker"]
    Redis --> Worker["Celery worker"]
    Worker --> DB
```

Application boundaries remain small and explicit:

```text
Router -> Service -> Repository -> Database
Worker -> Service -> Repository -> Database
Celery task -> testable worker-processing function
```

- The router owns HTTP concerns.
- The service owns job use cases.
- The repository owns persistence and guarded transitions.
- The Celery task is a thin wrapper around testable worker logic.

Tasks carry only a `job_id`. The worker loads the latest payload and state from
PostgreSQL before attempting a guarded claim.

## Job Lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: claim
    running --> completed: success
    running --> failed: permanent failure
    running --> retrying: retryable failure
    retrying --> running: reclaim
    retrying --> failed: retry limit exhausted
```

| Status | Meaning |
|---|---|
| `queued` | Waiting to be claimed. |
| `running` | Claimed and being processed. |
| `retrying` | Waiting for another attempt. |
| `completed` | Finished successfully. |
| `failed` | Permanently failed or recovered as stuck. |

Only `queued` and `retrying` jobs are claimable. `completed` and `failed` are
terminal.

Claiming is performed with a conditional database update. Two workers may
receive the same task, but only one can transition the job from a claimable state
to `running`. The `attempts` counter increases only when that transition succeeds.

## Quick Start

Start PostgreSQL and Redis:

```bash
docker compose up -d postgres redis
```

Apply migrations:

```bash
docker compose run --rm api alembic upgrade head
```

Start the API and worker:

```bash
docker compose up --build api worker
```

The API is available at `http://localhost:8001` and its OpenAPI documentation at
`http://localhost:8001/docs`.

View worker logs:

```bash
docker compose logs -f worker
```

Stop the stack with `docker compose down`. Use `docker compose down -v` only when
you also want to delete local PostgreSQL data.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/jobs` | Create and enqueue a job. |
| `GET` | `/jobs/{job_id}` | Read durable state and result. |
| `GET` | `/jobs` | Filter and paginate jobs. |

### Create a Job

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "hello backend"}}'
```

The endpoint returns `201 Created` with a persisted job in `queued`. Submission
does not mean the background work has completed.

Add an optional idempotency key when clients may repeat a submission:

```bash
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "payload": {"text": "same request"},
    "idempotency_key": "demo-123"
  }'
```

Repeating the same key returns the existing job without intentionally enqueueing
another task. This deduplicates job creation, not execution or side effects.

### Read and List Jobs

```bash
curl http://localhost:8001/jobs/1
curl "http://localhost:8001/jobs?status=failed&limit=20&offset=0"
```

List behavior:

- `status` is optional and accepts any lifecycle status;
- `limit` accepts 1-100;
- `offset` must be non-negative;
- results are ordered newest first;
- responses include `items`, `limit`, `offset`, and total matching `count`.

Unknown job IDs return `404`; invalid query parameters return `422`.

## Failure and Retry Behavior

The demo processor exposes two deterministic failure inputs.

```bash
# Non-retryable: becomes failed immediately
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "bad input", "fail": true}}'

# Retryable: enters retrying and eventually fails after the retry limit
curl -X POST http://localhost:8001/jobs \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "temporary issue", "transient_fail": true}}'
```

The retry policy allows three retries after the initial attempt. Countdown values
are 1, 2, and 4 seconds, with a 30-second upper bound. Before each retry, the
latest error is persisted and the next delivery must claim the job again.

## Stuck-Job Recovery

A worker can stop after claiming a job but before persisting its final state. The
service exposes:

```python
recover_stuck_jobs(timeout_minutes=10)
```

Recovery fails old `running` jobs instead of automatically requeueing work whose
previous outcome is uncertain. Its write succeeds only if the job is still
`running` and the observed `started_at` has not changed.

Recovery is manually invoked. Scheduling, leases, heartbeats, fencing, and full
stale-worker protection remain out of scope.

## Lifecycle Logging

Logs use stable events such as `job_created`, `job_claimed`, `job_retrying`,
`job_retry_scheduled`, `job_completed`, `job_failed`, `job_skipped`, and
`stuck_job_recovered`.

```text
event=job_claimed job_id=42 status=running attempts=2
event=job_completed job_id=42 status=completed attempts=2
```

This is lightweight lifecycle logging, not durable event history or a
centralized observability stack.

## Tests

Run the fast test suite:

```bash
pytest -q
```

It covers API, service, repository, worker lifecycle, retry, duplicate delivery,
idempotency, listing, and recovery behavior without requiring a live broker.

Run the multi-service smoke test:

```bash
./scripts/e2e_smoke.sh
```

The script starts a clean Docker Compose stack, applies migrations, and verifies
successful completion, persisted failure, duplicate idempotency behavior, and
filtered job listing. It exits non-zero on failure and cleans up on exit.

GitHub Actions runs `pytest -q` with Python 3.12 on pushes and pull requests. The
Docker smoke test remains a manual integration check.

## Decisions and Boundaries

- [Architecture decisions](docs/decisions.md)
- [Production boundaries](docs/production-boundaries.md)

Important non-guarantees include:

- no exactly-once execution or side effects;
- no atomic database-to-broker publication;
- no automatic scheduled recovery or dead-letter workflow;
- no full stale-worker fencing;
- no production observability or deployment hardening.

The project intentionally avoids expanding into Kafka, Kubernetes, multiple job
types, priority queues, an admin dashboard, distributed locking, or a complete
monitoring stack without a concrete operational need.
