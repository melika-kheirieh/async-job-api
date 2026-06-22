# Production Boundaries

This document describes the guarantees and limitations of the current Async Job
API. The project is production-aware, but it is not presented as a complete
production job platform.

## Current Guarantees

- PostgreSQL stores the durable job state and lifecycle metadata.
- Only `queued` and `retrying` jobs may be claimed for processing.
- Claiming is a conditional database transition.
- `attempts` increases only when a claim succeeds.
- Retryable failures enter an explicit `retrying` state.
- Retries are bounded and use exponential backoff.
- Non-retryable failures and exhausted retries become `failed`.
- Terminal jobs cannot be claimed again.
- Idempotency keys prevent duplicate job rows for the same key.
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
- durable lifecycle event history;
- full protection from stale workers;
- zero data loss under infrastructure failure;
- production-grade availability, monitoring, or security.

An idempotency key deduplicates job creation requests. It does not make the job
handler or its external side effects idempotent.

## Failure Modes Handled

The system explicitly handles:

- non-retryable processing failures;
- retryable failures with a bounded retry policy;
- retry exhaustion;
- duplicate task delivery for jobs that are no longer claimable;
- duplicate creation requests using the same idempotency key;
- concurrent idempotency-key insertion through a database uniqueness constraint;
- missing jobs received by a worker;
- stale jobs left in `running`;
- unexpected worker-processing exceptions;
- visibility of failure details through persisted state and lifecycle logs.

Stuck-job recovery is currently invoked explicitly. It is not automatically
scheduled.

## Race Conditions Handled

The current design protects against:

- two workers successfully claiming the same claimable job concurrently;
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
- a durable audit-event table.

These features should be introduced only when their operational need and
ownership model are clear.