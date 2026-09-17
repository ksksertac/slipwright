---
domain: devops
tags: [ci, github-actions, docker, deployment, pull-requests, secrets, infrastructure, monitoring]
applies_to: [github, docker, compose, kubernetes, terraform, any]
---

# Delivery and infrastructure

## Pull requests

One PR per job branch, titled in the imperative under 70 characters, with a body that
says what changed, why, how it was tested and what the reviewer should look at first.
Link the tracker issue. Keep the branch rebased on the base branch; never merge the base
into the feature branch repeatedly. A PR that changes infrastructure includes the plan
output (`terraform plan`, migration SQL) in the description.

## Continuous integration

CI runs on every push: lint, type-check, unit tests, integration tests with services
from `docker compose`, and a build of every artefact. The pipeline is defined in the
repository, uses pinned action/image versions, caches dependencies by lockfile hash, and
fails fast on the cheapest check. Red CI blocks merge; do not retry a red run without a
fix unless the failure is a known flake with an open issue.

## Containers

Multi-stage Dockerfiles; the runtime image contains only what runs (no compilers, no
dev dependencies, no source of the build stage). Pin base images by tag and refresh
monthly. Run as a non-root user where the workload allows. Every image has a
`HEALTHCHECK` and exposes configuration through environment variables only. Never bake
secrets into layers or build args.

## Deployment

Deployments are declarative (compose, Helm, Terraform) and idempotent; a rerun with no
changes changes nothing. Roll out with health checks and a rollback path that is tested
before it is needed. Database migrations run before the new version serves traffic and
are backward compatible with the version still running. Feature flags gate risky
behaviour so a rollback is a flag flip, not a redeploy.

## Secrets and access

Secrets live in the platform's secret manager and reach the process as environment
variables at start; never in the repository, CI logs or images. Rotate on every
departure and on any suspected leak. CI tokens are scoped to the minimum (contents:
write, pull-requests: write) and expire. Production access is by role, audited, and
never shared.

## Monitoring and on-call

Every service ships with a dashboard (traffic, errors, latency, saturation) and alerts
on symptoms users feel (error rate, p95 latency, queue lag), not on causes. Alerts have a
runbook link. Log retention and PII rules are written down. After an incident, a short
blameless write-up with actions goes into the repository.

## Fixing red CI

When CI fails on a job branch, read the failing step's log first; fix the cause in the
smallest change; do not disable the step, loosen the check or bump timeouts to hide a
real failure. If the failure is unrelated flakiness, say so in the summary with the log
excerpt so a human can decide.
