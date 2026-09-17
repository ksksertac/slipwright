---
domain: product
tags: [backlog, epics, stories, tasks, acceptance, scope, jira]
applies_to: [all]
---

# Product backlog

## Reading the product before writing the backlog

Start from the manifest (`pyproject.toml`, `package.json`, `go.mod`, `pom.xml`, …),
the lockfile, the CI configuration and the README; they say more than the tree. Detect
the package manager from the lockfile that exists (`uv.lock`, `package-lock.json`,
`pnpm-lock.yaml`), not from habit. Note monorepos (several manifests) and name the
package the request concerns.

## What a task must say

A task is done when a tester can verify it without asking: name the user-visible
behaviour, the inputs and the expected outcome, and any rule or limit that applies.
Tasks that hide a technical choice ("use Redis") are wrong — say the need ("responses
under 200 ms") and let the Architect choose. One task, one specialist: if a task needs
both a backend change and a screen, write two tasks and say which comes first.

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
