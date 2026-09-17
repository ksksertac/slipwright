---
domain: backend
tags: [database, migrations, transactions, kafka, events, retry, dead-letter, logging, observability]
applies_to: [python, fastapi, sqlalchemy, postgres, kafka, any]
---

# Data, messaging and observability

## Migrations

Every schema change is a migration file checked in with the code that needs it, written
so it can run on a live system: add columns as nullable or with a default, backfill in a
separate step, then tighten constraints. Never rename a column in place — add the new
one, migrate data, drop the old one in a later release. Migrations have a down step or
document why they cannot be reversed. Run them in CI against an empty database and
against a snapshot with data.

## Transactions and consistency

One request, one transaction, opened as late and closed as early as possible. Do not
hold a transaction across a network call. Use `SELECT … FOR UPDATE` (or optimistic
version columns) for read-modify-write on money or inventory. Unique constraints in the
database are the source of truth for uniqueness; application checks are only for nicer
errors.

## Kafka consumers and retries

Consumers are idempotent: processing the same message twice must be harmless (dedupe on
the event id stored with the result). Commit offsets only after the side effect is
durable. On a transient failure retry in-process with exponential backoff (base 1 s,
factor 2, maximum 5 attempts, jitter); on a permanent failure (bad payload, business
rule) do not retry — publish to `<topic>.dlq` with the error and the original headers,
commit, and alert. Never block the partition indefinitely and never drop a message
silently. Poison messages must not stop the consumer group.

## Event contracts

Events are versioned JSON with `event_id`, `event_type`, `occurred_at`, `producer` and
`schema_version` in every envelope. Producers never remove or retype fields; consumers
ignore unknown fields. Topic names are `<domain>.<entity>.<event>` in lowercase
(`billing.invoice.paid`). Payloads carry ids and the facts that changed, not whole
aggregates from other services.

## Logging

Structured logs (JSON in production) with `level`, `message`, `correlation_id`,
`service`, and the ids relevant to the request (`user_id`, `invoice_id`). Log at INFO
for state changes and external calls, WARNING for handled anomalies, ERROR only when
something needs a human. Never log secrets, tokens, full card numbers or personal data
beyond ids. One log line per event — no multi-line dumps in production.

## Metrics and tracing

Expose request count, latency histogram and error rate per endpoint, plus queue lag per
consumer, in the format the project already uses (Prometheus, OpenTelemetry). Propagate
the trace/correlation id across HTTP and message headers. Add a health endpoint that
checks the database and the broker with short timeouts and reports each dependency
separately.

## Configuration

Configuration comes from the environment (twelve-factor), validated at startup into a
typed settings object; fail fast on missing or malformed values. No defaults for
secrets, sensible defaults for everything else, and every setting documented in the
README table.
