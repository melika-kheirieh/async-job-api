# Architecture Decisions

This document records the main reliability and architecture decisions behind the
Async Job API. It explains both the chosen approach and its intentional limits.

## 1. PostgreSQL Is the Source of Truth

PostgreSQL owns the durable job state, including status, payload, result, error
details, attempt count, idempotency key, and lifecycle timestamps.

That gives the API and worker one queryable, transactional place for lifecycle
reads, guarded writes, list filtering, and idempotency-key uniqueness.

Redis is not treated as authoritative job storage. If Celery delivery and
database state disagree, the database state decides whether a job may be
processed.

## 2. Redis Is Delivery Infrastructure, Not Job State

Redis coordinates Celery delivery between the API and workers. It does not own
the job lifecycle, and the API does not serve job status from Redis.

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
attempt. It also makes retry backoff visible through the API instead of hiding
that state inside Celery. A job becomes `failed` when the error is
non-retryable or the retry limit has been exhausted.

## 6. Cancellation Is a Guarded Waiting-State Transition

Only jobs in `queued` or `retrying` may transition to `canceled`.

Cancellation is implemented as a conditional database update. It prevents future
processing according to the durable database state, but it does not remove
already-published Celery messages from Redis.

If Celery later delivers a task for a canceled job, the worker loads the latest
state from PostgreSQL, fails to claim the job, and skips processing it. This
keeps cancellation simple and database-authoritative without adding broker-level
message management.

Running and terminal jobs are not cancelable in the current design.

## 7. Idempotency Prevents Duplicate Job Creation

The optional idempotency key has a database uniqueness constraint. Repeating a
creation request with the same key returns the existing job and does not
intentionally enqueue another task.

This is request deduplication, not an exactly-once processing guarantee.
Clients are expected to reuse a key only for the same logical request; the API
does not reconcile conflicting payloads submitted with the same key.
Duplicate side effects still require idempotent job handlers and, where
applicable, idempotency support from external systems.

## 8. Stuck Jobs Fail Closed Instead of Being Requeued

A stale `running` job has an uncertain outcome. Its work may not have started, or
a side effect may have completed before the worker stopped updating the database.

The current recovery policy marks these jobs as `failed` rather than requeueing
them automatically. This makes the uncertainty visible and avoids blind
duplicate execution.

Recovery uses a conditional transition so it does not overwrite a job whose
status or execution start time changed after discovery. Automatic scheduling,
leases, heartbeats, fencing tokens, and job-specific recovery policies remain
outside the current scope. Manual recovery is exposed through an operational CLI.

## 9. The Worker Orchestrates, While the Processor Interprets Payloads

The Celery worker owns orchestration: database session lifecycle, guarded claim,
completion, failure, retry scheduling, and lifecycle logging.

The demo processor owns payload interpretation. It decides whether a payload
should succeed, raise a retryable error, or raise a non-retryable error.

This keeps the worker boundary focused on job lifecycle mechanics instead of
mixing orchestration with demo business logic. Adding real job types would
require explicit processor boundaries and idempotent side-effect handling rather
than expanding the worker task directly.

## 10. Unit Tests Are Brokerless, While the Smoke Test Is Multi-Service

Unit, service, processor, and worker tests exercise lifecycle rules without
requiring a live Redis broker or Celery worker. This keeps correctness tests
fast, deterministic, and focused.

The Docker smoke test covers a different responsibility: it verifies that the
API, PostgreSQL, migrations, Redis, and Celery worker function together.

Neither test layer replaces the other.
