---
domain: analysis
tags: [profile, build, test, run, repository, planning, breakdown, estimation]
applies_to: [all]
---

# Analysis and planning

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

## Writing a plan

Phases are small, ordered and independently verifiable: each one can pass the build
gate on its own. Backend contracts come before the front-ends that consume them. One
domain per phase (backend, web, mobile, infra, docs). Name the files each phase will
touch — it is how the developer's context is chosen. Three to eight phases is typical;
more means the request should be split into separate developments.

## Epics, stories and tasks

An epic is an outcome the requester recognises; a story is one user-visible capability
within it; a task is one phase. Titles are short and specific ("Retry webhook delivery
with backoff", not "Webhook improvements"). Descriptions say what done looks like, in one
or two sentences a tester could turn into cases.

## When to stop and ask

If the request is ambiguous in a way that changes the design (two plausible readings
lead to different phases), if it requires a dependency or service the repository does
not have, or if it conflicts with a core rule, do not guess: describe the ambiguity in
`summary` so the human can decide at the gate.
