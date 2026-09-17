---
domain: architecture
tags: [profile, build, test, run, phases, decisions, contracts, repository]
applies_to: [all]
---

# Architecture and planning

## Reading a repository

Start from the manifest (`pyproject.toml`, `package.json`, `go.mod`, `pom.xml`, …),
the lockfile, the CI configuration and the README; they say more than the tree. Detect
the package manager from the lockfile that exists (`uv.lock`, `package-lock.json`,
`pnpm-lock.yaml`), not from habit. Note monorepos (several manifests) and name the
package the request concerns.

## Choosing build, test and run commands

Prefer the commands CI already runs; they are known to work. The build command must
include the linters and type checks the project uses; the test command runs the whole
suite non-interactively with quiet output. The run command starts the service on the
literal `{port}` placeholder and must not daemonise. Never invent a command the
repository does not support — say what is missing instead.

## Writing the phases

Phases are small, ordered and independently verifiable: each one can pass the build
gate on its own and implements exactly one backlog task. Backend contracts come before
the front-ends that consume them. One domain per phase (backend, web, mobile, infra,
docs). Name the files each phase will touch — it is how the specialist's context is
chosen. If a task cannot be one phase in one domain, say so in `summary` so the backlog
is split, instead of mixing domains.

## Decisions worth recording

Write a decision when a reviewer would otherwise ask "why this way": a new component or
dependency, a data model change and its migration, a contract between backend and a
front-end (endpoint, payload, error codes), a trade-off taken (consistency over
latency, …), anything that constrains later phases. One sentence each, stating the
choice and the reason. Skip decisions that only restate the request.

## Contracts between domains

When backend and front-end phases share a contract, the backend phase defines it
explicitly (paths, methods, request and response shapes, error codes, pagination) and the
front-end phase consumes exactly that. Put the contract in the decisions so both
specialists see the same text. Prefer extending an existing endpoint over adding a
near-duplicate.

## When to stop and ask

If the backlog is ambiguous in a way that changes the design (two plausible readings
lead to different phases), if it requires a dependency or service the repository does
not have, or if it conflicts with a core rule, do not guess: describe the ambiguity in
`summary` so the human can decide at the gate.
