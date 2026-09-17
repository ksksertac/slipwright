# Slipwright — Build Task List

A multi-agent SDLC harness. Analyst, Planner, Developer, QA and DevOps agents run each
job in its own git worktree, with human approval gates between phases.

## How to use this file

- Work on **one task at a time**, in order. Do not start a task whose dependencies are unmet.
- A task is done only when every item under **Done when** is true and verified by running it.
- After each task: run the test suite, commit with a message referencing the task ID.
- If a task's design conflicts with something you discover in the code, stop and ask
  rather than improvising a different architecture.
- Mark a task `[x]` only after all its **Done when** items are verified.

## Stack

- Python 3.12, FastAPI, `uv` for dependency management
- SQLite for job state (single file, no server)
- pytest for tests
- Docker + docker compose for per-job live environments

## Non-negotiable invariants

These hold at every point in the build. If a task seems to require breaking one, stop and ask.

1. **No model name is ever hardcoded in engine code.** Model and thinking depth are read
   from the project profile, per role.
2. **Approval gates are enforced by the state machine**, never by prompt instructions.
   An agent for the next phase is not invoked at all while a job is in an approval state.
3. **Job state survives process death.** Killing the server mid-job and restarting it
   resumes from the last committed state.
4. **Jobs never share a checkout.** One git worktree per job, one port per job.

---

## Progress

> **Resume here:** Phases 0 and 1 are complete. Next task is **T2.2 — Agent invocation layer (in-progress)**.
> Design note for T1.3: `run_cmd` is executed as a subprocess in the worktree (Docker is used
> only if the profile's `run_cmd` itself invokes it).

| Phase | Task | Status |
|-------|------|--------|
| 0 | T0.1 Repository skeleton | [x] |
| 0 | T0.2 Profile schema | [x] |
| 0 | T0.3 Job schema and store | [x] |
| 1 | T1.1 Worktree lifecycle | [x] |
| 1 | T1.2 Port allocation | [x] |
| 1 | T1.3 Live environment | [x] |
| 2 | T2.1 Orchestrator state machine | [x] |
| 2 | T2.2 Agent invocation layer | [ ] |
| 2 | T2.3 Analyst role | [ ] |
| 2 | T2.4 Minimal API and CLI | [ ] |
| 3 | T3.1 Planner role | [ ] |
| 3 | T3.2 Developer role, phase by phase | [ ] |
| 3 | T3.3 Build gate | [ ] |
| 4 | T4.1 QA role, two stages | [ ] |
| 4 | T4.2 DevOps role | [ ] |
| 5 | T5.1 Inbox steering | [ ] |
| 5 | T5.2 Per-role model routing, verified | [ ] |
| 5 | T5.3 Job dashboard | [ ] |

---

## Phase 0 — Contracts

### T0.1 — Repository skeleton
Create the project layout and tooling.

**Done when**
- [x] `pyproject.toml` with the stack above; `uv sync` succeeds from a clean clone
- [x] Package layout exists: `slipwright/{orchestrator,roles,gates,workspace,store,api}/`
- [x] `pytest` runs and collects zero tests without error
- [x] `ruff` and `mypy` configured and passing

### T0.2 — Profile schema
Define the project profile: the file that makes the engine project-agnostic.

**Done when**
- [x] `slipwright/schemas/profile.py` defines a pydantic model with: language, package manager,
  `build_cmd`, `test_cmd`, `run_cmd`, `port`, and a `roles` map where every role has
  `model`, `thinking_depth`, and `permissions`
- [x] A JSON Schema is exported to `schemas/profile.schema.json`
- [x] Round-trip tests: valid profile loads, invalid profile raises with a readable error
- [x] An example profile for a Python FastAPI project lives in `examples/`

### T0.3 — Job schema and store
Define job state and its persistence layer.

**Done when**
- [x] A `Job` model exists with: id, repo path, worktree path, port, current state,
  profile, and an append-only `history` of phase transitions
- [x] `slipwright/store/` persists jobs to SQLite; `get`, `create`, `update_state`, `list`
- [x] Every state transition writes to `history` with a timestamp — never overwrites
- [x] Tests cover: create, read back after reopening the connection, transition appends

---

## Phase 1 — Isolation

### T1.1 — Worktree lifecycle
Give each job its own checkout.

**Done when**
- [x] `workspace.create(job)` runs `git worktree add` on a new branch `slipwright/<job-id>`
- [x] `workspace.destroy(job)` removes the worktree and deletes the branch
- [x] Two jobs can be created against the same repo simultaneously without interfering
- [x] A test creates two jobs, writes a different file in each, and asserts isolation
- [x] Failure to create a worktree leaves no partial state behind

### T1.2 — Port allocation
Give each job its own port.

**Done when**
- [x] A free port is found and recorded on the job at creation
- [x] Ports are released on destroy and never double-allocated across concurrent jobs
- [x] A test allocates ports for 10 concurrent jobs and asserts all are distinct

### T1.3 — Live environment
Bring up the project under test in isolation.

**Done when**
- [x] `workspace.up(job)` runs the profile's `run_cmd` inside the worktree on the job's port
- [x] `workspace.down(job)` tears it down and frees the port
- [x] Logs are captured to a per-job file, not to stdout
- [x] A health check confirms the port answers before `up` returns

---

## Phase 2 — State machine and first role

### T2.1 — Orchestrator state machine
The core. No agents yet — transitions only.

**Done when**
- [x] States are explicit: `created`, `analyzing`, `awaiting_profile_approval`, `planning`,
  `awaiting_plan_approval`, `developing`, `build_gate`, `qa`, `awaiting_test_approval`,
  `devops`, `done`, `failed`
- [x] Illegal transitions raise; every legal transition is persisted before side effects run
- [x] `resume(job)` inspects persisted state and continues from it
- [x] Tests drive a job through every legal path with stub phase handlers

### T2.2 — Agent invocation layer
One place where the engine talks to a model.

**Done when**
- [ ] A single `invoke_role(role, profile, context) -> RoleResult` entry point exists
- [ ] Model and thinking depth come from `profile.roles[role]` — grep the engine for hardcoded
  model strings and find none
- [ ] Structured output is parsed and validated against a per-role result schema
- [ ] Failures (timeout, malformed output) return a typed error, never a raw exception upward

### T2.3 — Analyst role
The first real agent.

**Done when**
- [ ] Analyst scans the worktree and emits a profile matching `profile.schema.json`
- [ ] On success the job moves to `awaiting_profile_approval` and **stops**
- [ ] `POST /jobs/{id}/approve` resumes; `POST /jobs/{id}/reject` with feedback re-runs Analyst
- [ ] Integration test: start a job, kill the process, restart, assert the job is still
  awaiting approval and still resumable

### T2.4 — Minimal API and CLI
Enough surface to drive a job by hand.

**Done when**
- [ ] `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, approve/reject endpoints
- [ ] CLI wraps these: `slipwright new`, `slipwright status`, `slipwright approve`
- [ ] `GET /jobs/{id}` shows current state and phase history

---

## Phase 3 — Planner, Developer, build gate

### T3.1 — Planner role
**Done when**
- [ ] Planner produces a structured plan: ordered phases, each with a goal and changed files
- [ ] Job moves to `awaiting_plan_approval` and stops
- [ ] Reject with feedback re-runs Planner with the feedback in context, bounded to 3 rounds

### T3.2 — Developer role, phase by phase
**Done when**
- [ ] Developer executes one plan phase per invocation, not the whole plan at once
- [ ] Phase progress is persisted after each phase, so a restart resumes mid-plan
- [ ] Each phase's diff is recorded in job history

### T3.3 — Build gate
**Done when**
- [ ] After each Developer phase, the profile's `build_cmd` and `test_cmd` run in the worktree
- [ ] Non-zero exit returns the captured output to Developer for a fix attempt
- [ ] Maximum 3 attempts, then the job moves to `failed` with the last output attached
- [ ] Tests cover: pass first try, pass on retry, exhaust retries

---

## Phase 4 — QA and DevOps

### T4.1 — QA role, two stages
**Done when**
- [ ] Stage one: QA emits a test case list; job moves to `awaiting_test_approval` and stops
- [ ] The human can add and remove cases; edits are persisted on the job
- [ ] Stage two: QA writes tests for the approved list only
- [ ] New tests run through the same build gate before the job advances

### T4.2 — DevOps role
**Done when**
- [ ] Opens a PR from the job's branch with a description built from the plan and phase history
- [ ] Polls CI status until terminal
- [ ] On red CI, feeds the failure log back for a fix, bounded to 3 attempts
- [ ] DevOps is configured with a smaller model in the example profile — verify the engine
  honours it and does not fall back to the default

---

## Phase 5 — Steering and routing

### T5.1 — Inbox steering
Let the human redirect a job that is already running.

**Done when**
- [ ] `POST /jobs/{id}/message` appends to a per-job inbox
- [ ] Every role invocation drains the inbox and injects pending messages into its context
- [ ] Consumed messages are marked and recorded in history, never replayed
- [ ] Test: queue a message mid-plan, assert the next Developer invocation sees it

### T5.2 — Per-role model routing, verified
**Done when**
- [ ] A test asserts each role was invoked with exactly the model named in the profile
- [ ] Switching a role's model in the profile changes behaviour with no engine code change
- [ ] README documents how to tune model and thinking depth per role

### T5.3 — Job dashboard
**Done when**
- [ ] A single page lists jobs with state, current phase, and pending approvals
- [ ] Approve and reject are actionable from the page
- [ ] Phase history and diffs are viewable per job

---

## Definition of done for the whole build

- [ ] Two jobs run concurrently against the same repo, end to end, without interference
- [ ] Killing the server at any phase and restarting resumes every in-flight job
- [ ] No engine module references a model name
- [ ] A job cannot advance past any approval state without an explicit approve call
