# Operations Runbook

This runbook describes how to diagnose common operational issues in the Async Job API project.

The project uses:

- FastAPI for the HTTP API
- PostgreSQL as the source of truth for job state
- Redis as the Celery broker
- Celery workers for background execution
- Alembic for database migrations

This is a local/demo operations guide, not a production incident process.

## Quick Checks

Start with these commands:

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f postgres
docker compose logs -f redis
````

Check API health through the OpenAPI page:

```bash
open http://localhost:8001/docs
```

Run the fast test suite:

```bash
pytest -q
```

Run the Docker smoke test:

```bash
./scripts/e2e_smoke.sh
```

## API Does Not Start

Common causes:

* environment variables are missing or invalid
* PostgreSQL is not reachable
* migrations were not applied
* Docker image was not rebuilt after dependency or code changes

Check service logs:

```bash
docker compose logs -f api
```

Check database and Redis containers:

```bash
docker compose ps
```

Rebuild and restart:

```bash
docker compose up --build api
```

If the database schema is behind, apply migrations:

```bash
docker compose run --rm api alembic upgrade head
```

## Worker Is Not Processing Jobs

Symptoms:

* jobs stay in `queued`
* API accepts jobs, but no result appears
* worker logs are empty or show broker errors

Check worker logs:

```bash
docker compose logs -f worker
```

Check Redis:

```bash
docker compose ps redis
docker compose logs -f redis
```

Restart worker:

```bash
docker compose up --build worker
```

Important: job state lives in PostgreSQL. Redis only coordinates Celery task delivery.

## Redis Is Unavailable

Symptoms:

* job creation may fail when the API tries to enqueue a task
* worker cannot receive tasks
* logs mention broker connection errors

Check Redis status:

```bash
docker compose ps redis
docker compose logs -f redis
```

Restart Redis and dependent services:

```bash
docker compose up -d redis
docker compose up --build api worker
```

If a job was created but not delivered to Celery, inspect its status through the API:

```bash
curl http://localhost:8001/jobs
```

## PostgreSQL Is Unavailable

Symptoms:

* API returns database errors
* worker cannot load or update jobs
* migrations fail

Check PostgreSQL:

```bash
docker compose ps postgres
docker compose logs -f postgres
```

Restart PostgreSQL:

```bash
docker compose up -d postgres
```

Then apply migrations:

```bash
docker compose run --rm api alembic upgrade head
```

## Migrations Are Missing Or Schema Is Behind

Symptoms:

* API or worker fails with missing column/type/index errors
* Alembic head does not match expected project state
* enum values such as `RETRYING` or `CANCELED` are missing

Check migration state:

```bash
alembic heads
alembic history
```

Apply migrations:

```bash
alembic upgrade head
```

In Docker:

```bash
docker compose run --rm api alembic upgrade head
```

Expected rule: there should be exactly one Alembic head.

## Job Is Stuck In Running

A job can remain in `running` if a worker stops after claiming it but before persisting a final state.

Inspect jobs:

```bash
curl "http://localhost:8001/jobs?status=running"
```

Run manual recovery:

```bash
python -m app.cli.recover_stuck_jobs --timeout-minutes 10
```

Docker example:

```bash
docker compose run --rm api python -m app.cli.recover_stuck_jobs --timeout-minutes 10
```

Recovery behavior:

* only old `running` jobs are considered
* recovered jobs become `failed`
* recovery uses a guarded transition
* recovery does not requeue work automatically

This is conservative because the previous worker outcome may be unknown.

## Job Is Stuck In Retrying

A `retrying` job means the worker saw a retryable failure and scheduled another Celery delivery.

Check worker logs:

```bash
docker compose logs -f worker
```

Inspect retrying jobs:

```bash
curl "http://localhost:8001/jobs?status=retrying"
```

If the job never leaves `retrying`, check:

* worker is running
* Redis is available
* retry countdown has elapsed
* the payload still triggers a retryable failure

Retry scheduling is handled by Celery. PostgreSQL stores the visible job state.

## Job Failed After Retries

A job with retryable failures eventually becomes `failed` after the retry limit is exceeded.

Inspect failed jobs:

```bash
curl "http://localhost:8001/jobs?status=failed"
```

Check `error_message` to distinguish:

* permanent payload failure
* retry limit exceeded
* stuck job recovery

This project does not automatically requeue failed jobs. Retrying failed jobs manually is intentionally out of scope.

## Canceling Jobs

Only waiting jobs can be canceled:

* `queued`
* `retrying`

Cancel a job:

```bash
curl -X POST http://localhost:8001/jobs/1/cancel
```

Expected behavior:

* `queued` -> `canceled`
* `retrying` -> `canceled`
* `running` -> `409 Conflict`
* `completed` -> `409 Conflict`
* `failed` -> `409 Conflict`
* `canceled` -> `409 Conflict`
* missing job job -> `404 Not Found`

Canceling a job does not remove Celery messages from Redis. If Celery later delivers the task, the worker loads the latest database state and skips canceled jobs.

## Duplicate Idempotency Key

If a client repeats a request with the same idempotency key, the API returns the existing job instead of intentionally creating a new one.

This protects job creation, not necessarily side effects inside a worker.

Check a job by ID:

```bash
curl http://localhost:8001/jobs/1
```

Use idempotency keys when clients may retry submissions after timeouts or network failures.

## Smoke Test Fails

Run:

```bash
./scripts/e2e_smoke.sh
```

If it fails, inspect:

```bash
docker compose ps
docker compose logs api
docker compose logs worker
docker compose logs postgres
docker compose logs redis
```

Common fixes:

```bash
docker compose down
docker compose up --build
```

If database state is stale and local data can be discarded:

```bash
docker compose down -v
docker compose up --build
```

Use `down -v` carefully because it deletes local PostgreSQL data.

## What This Runbook Does Not Cover

This project does not currently include:

* automatic recovery scheduling
* Celery Beat recovery jobs
* leases or heartbeat-based worker liveness
* fencing tokens
* durable event history
* manual failed-job requeue
* production authentication for admin operations

Those are intentionally outside the current scope.
