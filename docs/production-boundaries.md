# Production Boundaries

This document describes the guarantees and limitations of the current Async Job
API. The project is production-aware, but it is not presented as a complete
production job platform.

## Current Guarantees

- PostgreSQL stores the durable job state and lifecycle metadata.
- API-visible lifecycle state is read from PostgreSQL, not Redis.
- Only `queued` and `retrying` jobs may be claimed for processing.
- Claiming is a conditional database transition.
- `attempts` increases only when a claim succeeds.
- Retryable failures enter an explicit `retrying` state.
- Retries are bounded and use exponential backoff.
- Non-retryable failures and exhausted retries become `failed`.
- Only `queued` and `retrying` jobs may be canceled.
- Terminal jobs cannot be claimed again.
- Idempotency keys prevent duplicate job rows for the same key.
- Demo payload processing is separated from worker orchestration.
- Lifecycle events include the job ID and relevant execution context.
- Stuck-job recovery fails a candidate only if its observed execution state has
  not changed.

These guarantees assume that the database is available, migrations have been
applied, and the configured services are operating correctly.

## Non-Guarantees

The current system does not guarantee:

- exactly-once task delivery;
- exactly-once job execution;
- exactly-once external side effects;
- atomicity between committing a job and publishing its Celery task;
- automatic recovery of every lost or stuck task;
- removal of already-published Celery messages when a job is canceled;
- broker-level cancellation, message deletion, or Celery task revocation;
- cancellation of running work;
- durable lifecycle event history;
- full protection from stale workers;
- zero data loss under infrastructure failure;
- production-grade availability, monitoring, or security.

An idempotency key deduplicates job creation requests. It does not make the job
handler or its external side effects idempotent.

## Cancellation Limits

Cancellation is limited to jobs in `queued` or `retrying`. A successful
cancellation prevents future processing according to PostgreSQL state.

Cancellation does not revoke a Celery task, delete a Redis message, or interrupt
work that is already `running`. If Celery later delivers a task for a canceled
job, the worker reloads the database state, fails the guarded claim, and skips
the payload.

## Recovery Limits

Stuck-job recovery is currently invoked explicitly through the recovery CLI. It
marks old `running` jobs as `failed` through a guarded transition.

Recovery is not automatically scheduled, does not prove whether side effects
already happened, and does not requeue work. The local CLI is not an
authenticated or audited production operations surface.

## Failure Modes Handled

The system explicitly handles:

- non-retryable processing failures;
- retryable failures with a bounded retry policy;
- retry exhaustion;
- cancellation of waiting jobs;
- stale Celery delivery after cancellation, which is skipped by the claim guard;
- duplicate task delivery for jobs that are no longer claimable;
- duplicate creation requests using the same idempotency key;
- concurrent idempotency-key insertion through a database uniqueness constraint;
- missing jobs received by a worker;
- stale `running` jobs found by manual recovery;
- unexpected worker-processing exceptions;
- visibility of failure details through persisted state and lifecycle logs.

## Race Conditions Handled

The current design protects against:

- two workers successfully claiming the same claimable job concurrently;
- a worker processing a job after a successful cancellation transition;
- concurrent requests creating separate jobs with the same idempotency key;
- recovery overwriting a job that completed after being identified as stuck;
- recovery failing a newer execution whose start time changed after discovery.

These protections use conditional database transitions and uniqueness
constraints rather than process-local checks.

## Race Conditions Not Fully Handled

The current design does not fully protect against:

- a process crashing after the job commit but before task publication;
- a side effect succeeding before the worker records completion;
- a stale worker writing after recovery has already failed the job;
- duplicate side effects caused by retrying an uncertain external operation;
- automatic ownership transfer between workers;
- conflicting payloads submitted with the same idempotency key.

Leases, heartbeats, fencing tokens, transactional outbox delivery, and
idempotent handlers would be needed for stronger guarantees.

## Before Production Use

A production deployment would require decisions and implementation for:

- atomic or recoverable database-to-broker publication;
- idempotent business handlers and external operation keys;
- scheduled reconciliation and stuck-job recovery;
- authenticated and audited operational recovery commands;
- worker ownership, leases, heartbeats, or fencing;
- dead-letter handling and operational replay controls;
- metrics, alerting, tracing, and centralized logs;
- PostgreSQL concurrency and load testing;
- authentication, authorization, rate limiting, and secret management;
- backup, restore, deployment, and incident-response procedures.

The exact requirements depend on the business impact of each job type.

## Intentionally Out of Scope

The project intentionally does not add:

- Kafka or additional message brokers;
- Kubernetes;
- a full dead-letter queue workflow;
- Celery Beat scheduling;
- a distributed locking system;
- a monitoring stack;
- multiple job types or priority queues;
- an administration dashboard;
- broker-level cancellation or task revocation;
- a durable audit-event table.

These features should be introduced only when their operational need and
ownership model are clear.
