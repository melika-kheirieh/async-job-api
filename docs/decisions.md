# Architecture Decisions

This document records the main reliability and architecture decisions behind the
Async Job API. It explains both the chosen approach and its intentional limits.

## 1. PostgreSQL Is the Source of Truth

PostgreSQL owns the durable job state, including status, payload, result, error
details, attempt count, idempotency key, and lifecycle timestamps.

Redis is not treated as authoritative job storage. If message delivery and
database state disagree, the database state is used to decide whether a job may
be processed.

## 2. Redis Is Used Only as the Celery Broker

Redis coordinates task delivery between the API and Celery workers. It does not
own the job lifecycle.

Keeping status in both Redis and PostgreSQL would introduce synchronization and
conflict-resolution problems without providing enough value for this project.

## 3. Tasks Carry Only the Job ID

Celery tasks receive a job ID rather than a complete serialized job.

The worker loads the current payload and state from PostgreSQL before processing.
This keeps broker messages small, avoids stale job snapshots, and allows the
worker to apply database-backed claiming rules.

The trade-off is that workers require database availability during execution.

## 4. Job Claiming Uses a Guarded Database Transition

Only jobs in `queued` or `retrying` may transition to `running`.

The claim is implemented as a conditional database update. Attempt count and
execution timestamps are updated only when the claim succeeds.

This prevents two workers from successfully claiming the same job concurrently.
It does not provide a full exactly-once execution guarantee.

## 5. Retry State Is Explicit

A retryable failure moves the job from `running` to `retrying` while Celery
schedules the next attempt.

This distinguishes a job that is actively executing from one waiting for another
attempt. A job becomes `failed` when the error is non-retryable or the retry
limit has been exhausted.

## 6. Idempotency Prevents Duplicate Job Creation

The optional idempotency key has a database uniqueness constraint. Repeating a
creation request with the same key returns the existing job and does not
intentionally enqueue another task.

This is request deduplication, not an exactly-once processing guarantee.
Duplicate side effects still require idempotent job handlers and, where
applicable, idempotency support from external systems.

## 7. Stuck Jobs Fail Closed Instead of Being Requeued

A stale `running` job has an uncertain outcome. Its work may not have started, or
a side effect may have completed before the worker stopped updating the database.

The current recovery policy marks these jobs as `failed` rather than requeueing
them automatically. This makes the uncertainty visible and avoids blind
duplicate execution.

Recovery uses a conditional transition so it does not overwrite a job whose
status or execution start time changed after discovery. Automatic scheduling,
leases, heartbeats, fencing tokens, and job-specific recovery policies remain
outside the current scope.

## 8. Unit Tests Are Brokerless, While the Smoke Test Is Multi-Service

Unit, service, and worker tests exercise lifecycle rules without requiring a
live Redis broker or Celery worker. This keeps correctness tests fast,
deterministic, and focused.

The Docker smoke test covers a different responsibility: it verifies that the
API, PostgreSQL, migrations, Redis, and Celery worker function together.

Neither test layer replaces the other.