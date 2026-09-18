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
- React 19 + Vite + TypeScript for the web UI (`web/`), built to static files served by FastAPI

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

> **Resume here:** Phases 0–9 are complete (T9.0–T9.9). Next: whatever the user asks for; keep the invariants and the task-by-task rhythm.
> Design note for T1.3: `run_cmd` is executed as a subprocess in the worktree (Docker is used
> only if the profile's `run_cmd` itself invokes it).
> Design note for T2.2: `invoke_role` talks to a `ModelProvider` (`slipwright/providers/`);
> tests inject a fake provider, production defaults to `AnthropicProvider`. Providers return
> raw text; parsing and per-role schema validation (`slipwright/roles/results.py`) live in
> `slipwright/invoke.py` so all providers share one error path. `thinking_depth` maps to
> adaptive thinking + `output_config.effort` (`off` disables thinking).
> Design note for T2.3/T2.4: `slipwright/engine.py` drives phases; each working state has a
> handler, approval states have none. Jobs start from a **seed profile** (`--profile`); the
> Analyst proposes language/commands/port and the seed's `roles` are always kept, so model
> routing is never decided by a model. `Job.data` holds working state (plan, phase index,
> attempt counters, inbox); `Transition.detail` holds long-form records (profile JSON, diffs,
> build logs). The API runs phases in background tasks and resumes in-flight jobs on startup.
> `slipwright serve --provider scripted` runs the whole pipeline offline.
> Design note for Phase 3: the Developer returns full file contents (`FileChange`) and the
> engine writes them (enforcing `write_files`), stages, records the diff on the
> DEVELOPING→BUILD_GATE transition and commits each phase that passes the gate. Rejecting a
> plan more than 3 times fails the job.
> Design note for Phase 4: the state machine has no `qa -> devops` edge, so QA passes the
> `awaiting_test_approval` gate twice: `qa_stage=1` (case list proposed; the human may edit it
> via `PUT /jobs/{id}/tests`) and `qa_stage=2` (tests written and green through the same build
> gate). Approving stage 1 sends the job back to `qa`; approving stage 2 sends it to `devops`.
> DevOps talks to a `GitHost` (`slipwright/githost.py`, `gh`-backed); red CI goes to the
> Developer as a fix, max 3 attempts. The PR URL is persisted before polling so a restart
> never opens a second PR.
> Design note for Phase 5: every model call goes through `Engine._invoke`, which injects pending
> inbox messages (via `roles.common.base_context`) and afterwards marks them consumed and appends
> a same-state history entry (`inbox: N message(s) consumed by <role>`). The dashboard is
> server-rendered HTML under `/` and `/ui/...` with form posts; it shares the engine with the
> JSON API. The example profile gives DevOps `thinking_depth: off` because Haiku 4.5 rejects
> the `effort` parameter that other depths map to.
> Design note for T6.1: `Job.project_id` is optional on the model so workspace-level code and its tests can build bare jobs, but every job the engine or API creates belongs to a project (`create_job` finds or creates one for a bare `repo_path`). Projects without a checkout are cloned into `<state>/repos/<id>`; `clone_url` overrides the GitHub URL (tests clone local bare repos). A project's `profile` is the seed for its jobs (`Engine.seed_for`).
> Design note for T6.2: the breakdown lives inside `PlannerResult` (`breakdown.epics[].stories[].tasks[]`, task.phase is 1-based); a plan the model returns without one gets `default_breakdown` (one epic/story, one task per phase) before it is persisted. `slipwright/board.py` derives task/story/epic statuses from job state and `phase_index`; a job is on the board only once its plan is approved (`plan_is_active`).
> Design note for T6.3: `slipwright/activity.py` projects progress (`/projects/{id}/progress`) and the feed (`/projects/{id}/activity`) from job history; entries are classified by note prefix (`ActivityKind`, role) and carry the history index for `GET /jobs/{id}/history/{index}`. Shared pipeline test helpers live in `tests/pipeline.py`; `store`/`seed` fixtures in `conftest.py`.
> Design note for T6.4: `TestRun` rows live in `test_runs`; output goes to `<state>/test-runs/<id>.log`. `Engine.start_test_run` records a pending run and `execute_test_run` (background task in the API) runs `profile.test_cmd` under a per-checkout lock shared with the build gate; every gate execution is also recorded (`source=gate`). The main checkout's profile is the project's, else the newest approved job profile, else the seed (`Engine.project_profile`).
> Design note for T7.1: passwords are hashed with stdlib scrypt (memory-hard, no native dependency) instead of argon2/bcrypt; sessions and bearer tokens are random secrets stored as SHA-256 hashes (`slipwright/auth.py`, `store/users.py`). `create_app(require_auth=...)` attaches an app-wide dependency (`api/auth.py`) that exempts `/auth/login`, `/healthz` and the docs; tests pass `require_auth=False`. `slipwright user add` / `slipwright token new` work directly on the state dir.
> Design note for T7.2: `slipwright/secrets.py` (Fernet) encrypts settings flagged secret; the key comes from `SLIPWRIGHT_SECRET_KEY` or `<state>/secret.key`. `store/settings.py` is a name→JSON table; GitHub lives under `github` (owner, base_branch) and `github.token` (secret). `slipwright/github.py` is an httpx client (`Engine.http_transport` lets tests answer locally, see `tests/fakes.py`); `GhHost` passes the token as `GH_TOKEN` and clones embed it as `x-access-token`.
> Design note for T7.3: JSON routes are mounted on an `APIRouter` under `/api` (the old HTML dashboard stays at `/` and `/ui/...` until T8.7). `slipwright/events.py` is an in-process bus the store publishes to on every write; `GET /api/events` streams it as SSE (`project_id` filter, `limit` for scripts, keepalive pings). `schemas/openapi.json` is exported by `scripts/export_schema.py` and checked by `tests/test_phase7_api.py`; `SLIPWRIGHT_DEV=1` enables CORS for the Vite origin. The Phase 0–5 API tests were updated only in their URL prefixes.
> Design note for T7.4: `slipwright/jira.py` is the REST v3 client (basic auth, ADF bodies built from text); `slipwright/jirasync.py` reconciles a job idempotently (issue keys in `job.data.jira_keys`, last pushed statuses in `jira_status`, one-shot comments in `jira_marks`, outage in `jira_last_error`). The engine reconciles on entry to `_run` and after every handler, so approvals, restarts and failures all retry; each pass that did something is one `jira: N update(s)` history entry. Default issue types are Epic/Story/Subtask/Bug and default transitions To Do/In Progress/Done (per-project overrides in `Project.jira_transitions`).
> Design note for T7.5: `JiraAction` lives in `roles/results.py` (every `RoleOutput` may carry `jira_actions`); `slipwright/jiraactions.py` executes them through the agent account (`Engine.jira_client(agent=True)`, falling back to the human connection) after checking `Permission.JIRA` and project confinement. Idempotency keys are content hashes stored in `job.data.jira_done`; outages queue actions in `job.data.jira_queue`, retried by `_jira_reconcile`. Roles get a `jira` context section (keys, current task, transitions) only when permitted; every outcome is a `jira (<role>): ...` history entry.
> Design note for T8.1: `web/` is Vite 7 + React 19 + TypeScript (strict), React Router 7 and TanStack Query 5; `npm run build` writes `slipwright/api/static/` (gitignored) which `create_app` serves at `/` with an SPA fallback, or a 503 build hint when absent. `npm run gen:api` generates `src/api/schema.d.ts` from `schemas/openapi.json` with a SHA-256 header that `tests/test_phase8.py` and `npm run check:api` verify. The legacy dashboard moved to `/legacy` (retired in T8.7); only `/api` and `/legacy` require a session.
> Design note for T8.2: the OpenAPI export marks every property of response-only models as required (`_tighten_response_schemas`, since pydantic leaves defaulted fields optional), so the TypeScript client sees `job.id: string`, not `string | undefined`; input models keep their optional fields.
> Design note for T8.4: `PUT /api/jobs/{id}/profile` lets the human edit the Analyst's proposal before approving (engine `set_profile`, only in `awaiting_profile_approval`). Per-phase diffs and gate attempts are grouped from history notes (`developer phase N`, `build gate ... phase N`). Forms follow the server value until edited (state adjusted during render, no effects). `web/PARITY.md` is the legacy-dashboard parity list.
> Design note for T8.6: `GET /api/settings/profile` returns the engine's default seed so the Agents page can materialise a project's own profile (saved with `PATCH /api/projects/{id}`, validated server-side by pydantic). The generated client uses `defaultNonNullable: false` so defaulted input fields stay optional in TypeScript.
> Design note for T8.7: `slipwright/api/ui.py` and its T5.3 test are gone; the React app at `/` is the dashboard (`web/PARITY.md`). `tests/test_phase8_e2e.py` is the Phase 6–8 definition of done driven through the API exactly as the browser does it, with fake GitHub/Jira and the scripted provider.
> Design note for T9.1: `roles/specialists.py` maps `PlanPhase.domain` → role (`specialist_for`), holds the specialist instructions and the role→standards-domain map; `developer.run(as_role=...)` serves all four implementer roles; history notes are `<role> phase N/M`. `supervisor` is already in `RoleName` for T9.8. `/agents` cards come from `GET /api/agents` (`activity.agent_summaries`).
> Design note for T9.2: `slipwright/standards/__init__.py` loads pages (front-matter: domain/tags/applies_to), splits them into `##` chunks whose ids are content hashes, and lints them (`scripts/check_standards.py`, also run by tests). Project overrides live in `<repo>/.slipwright/standards/`; the Docker image copies `standards/`.
> Design note for T9.3: `standards/index.py` keeps chunks in `<state>/standards.sqlite3` (FTS5 with the porter tokenizer, heading-weighted BM25) plus optional embeddings (`none` / `openai` / `local` / `hashing`); ranking is reciprocal rank fusion of the two lists with a small bonus for project-scope chunks. `Engine.reindex_standards` is incremental by chunk id and skipped when a corpus fingerprint (paths, sizes, mtimes) is unchanged; `ensure_standards_indexed` runs before every search and at API startup.

| Phase | Task | Status |
|-------|------|--------|
| 0 | T0.1 Repository skeleton | [x] |
| 0 | T0.2 Profile schema | [x] |
| 0 | T0.3 Job schema and store | [x] |
| 1 | T1.1 Worktree lifecycle | [x] |
| 1 | T1.2 Port allocation | [x] |
| 1 | T1.3 Live environment | [x] |
| 2 | T2.1 Orchestrator state machine | [x] |
| 2 | T2.2 Agent invocation layer | [x] |
| 2 | T2.3 Analyst role | [x] |
| 2 | T2.4 Minimal API and CLI | [x] |
| 3 | T3.1 Planner role | [x] |
| 3 | T3.2 Developer role, phase by phase | [x] |
| 3 | T3.3 Build gate | [x] |
| 4 | T4.1 QA role, two stages | [x] |
| 4 | T4.2 DevOps role | [x] |
| 5 | T5.1 Inbox steering | [x] |
| 5 | T5.2 Per-role model routing, verified | [x] |
| 5 | T5.3 Job dashboard (replaced by the React app in T8.7) | [x] |
| 6 | T6.1 Project entity | [x] |
| 6 | T6.2 Work breakdown: epics, stories, tasks | [x] |
| 6 | T6.3 Progress and activity feed | [x] |
| 6 | T6.4 Test runs on demand | [x] |
| 7 | T7.1 Users and login | [x] |
| 7 | T7.2 Settings store and GitHub connection | [x] |
| 7 | T7.3 API namespace and live events | [x] |
| 7 | T7.4 Jira connection and issue sync | [x] |
| 7 | T7.5 Agents act in Jira | [x] |
| 7 | T7.6 Model providers: OpenAI and DeepSeek, keys in settings | [x] |
| 8 | T8.1 React app skeleton | [x] |
| 8 | T8.2 Login and projects list | [x] |
| 8 | T8.3 Project page: board, progress, developments | [x] |
| 8 | T8.4 Job page: gates, plan, diffs, steering | [x] |
| 8 | T8.5 Test results page | [x] |
| 8 | T8.6 Settings page: GitHub, Jira, agent access and users | [x] |
| 8 | T8.7 Retire the server-rendered dashboard | [x] |
| 8 | T8.8 Docker image and compose | [x] |
| 8 | T8.9 UI redesign: dashboard, cards, edit/delete flows, theme | [x] |
| 9 | T9.0 Role model: PO, Architect, QA (two new gates) | [x] |
| 9 | T9.1 Specialist agents: backend, web UI, mobile UI | [x] |
| 9 | T9.2 Standards corpus | [x] |
| 9 | T9.3 Standards index (RAG) | [x] |
| 9 | T9.4 Retrieval into every role's prompt | [x] |
| 9 | T9.5 Standards review gate | [x] |
| 9 | T9.6 Standards in the UI | [x] |
| 9 | T9.7 Orchestrator hardening: budgets, retries, supervisor decisions | [x] |
| 9 | T9.8 Supervisor at the gates: manual / assisted / auto | [x] |
| 9 | T9.9 Project pipeline view and bulk approvals | [x] |

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
- [x] A single `invoke_role(role, profile, context) -> RoleResult` entry point exists
- [x] Model and thinking depth come from `profile.roles[role]` — grep the engine for hardcoded
  model strings and find none
- [x] Structured output is parsed and validated against a per-role result schema
- [x] Failures (timeout, malformed output) return a typed error, never a raw exception upward

### T2.3 — Analyst role
The first real agent.

**Done when**
- [x] Analyst scans the worktree and emits a profile matching `profile.schema.json`
- [x] On success the job moves to `awaiting_profile_approval` and **stops**
- [x] `POST /jobs/{id}/approve` resumes; `POST /jobs/{id}/reject` with feedback re-runs Analyst
- [x] Integration test: start a job, kill the process, restart, assert the job is still
  awaiting approval and still resumable

### T2.4 — Minimal API and CLI
Enough surface to drive a job by hand.

**Done when**
- [x] `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, approve/reject endpoints
- [x] CLI wraps these: `slipwright new`, `slipwright status`, `slipwright approve`
- [x] `GET /jobs/{id}` shows current state and phase history

---

## Phase 3 — Planner, Developer, build gate

### T3.1 — Planner role
**Done when**
- [x] Planner produces a structured plan: ordered phases, each with a goal and changed files
- [x] Job moves to `awaiting_plan_approval` and stops
- [x] Reject with feedback re-runs Planner with the feedback in context, bounded to 3 rounds

### T3.2 — Developer role, phase by phase
**Done when**
- [x] Developer executes one plan phase per invocation, not the whole plan at once
- [x] Phase progress is persisted after each phase, so a restart resumes mid-plan
- [x] Each phase's diff is recorded in job history

### T3.3 — Build gate
**Done when**
- [x] After each Developer phase, the profile's `build_cmd` and `test_cmd` run in the worktree
- [x] Non-zero exit returns the captured output to Developer for a fix attempt
- [x] Maximum 3 attempts, then the job moves to `failed` with the last output attached
- [x] Tests cover: pass first try, pass on retry, exhaust retries

---

## Phase 4 — QA and DevOps

### T4.1 — QA role, two stages
**Done when**
- [x] Stage one: QA emits a test case list; job moves to `awaiting_test_approval` and stops
- [x] The human can add and remove cases; edits are persisted on the job
- [x] Stage two: QA writes tests for the approved list only
- [x] New tests run through the same build gate before the job advances

### T4.2 — DevOps role
**Done when**
- [x] Opens a PR from the job's branch with a description built from the plan and phase history
- [x] Polls CI status until terminal
- [x] On red CI, feeds the failure log back for a fix, bounded to 3 attempts
- [x] DevOps is configured with a smaller model in the example profile — verify the engine
  honours it and does not fall back to the default

---

## Phase 5 — Steering and routing

### T5.1 — Inbox steering
Let the human redirect a job that is already running.

**Done when**
- [x] `POST /jobs/{id}/message` appends to a per-job inbox
- [x] Every role invocation drains the inbox and injects pending messages into its context
- [x] Consumed messages are marked and recorded in history, never replayed
- [x] Test: queue a message mid-plan, assert the next Developer invocation sees it

### T5.2 — Per-role model routing, verified
**Done when**
- [x] A test asserts each role was invoked with exactly the model named in the profile
- [x] Switching a role's model in the profile changes behaviour with no engine code change
- [x] README documents how to tune model and thinking depth per role

### T5.3 — Job dashboard
**Done when**
- [x] A single page lists jobs with state, current phase, and pending approvals
- [x] Approve and reject are actionable from the page
- [x] Phase history and diffs are viewable per job

---

## Phase 6 — Projects and work breakdown

A **project** is a repository the user works on over time. A **job** (Phases 0–5) becomes one
"development" inside a project. The request the user types is broken down into
epics → stories → tasks; every task maps onto exactly one Developer plan phase, so the engine
and its invariants are unchanged.

### T6.1 — Project entity
**Done when**
- [x] `Project` model: id, name, description, `repo_path`, optional `github_repo`
  (`owner/name`), optional `jira_project_key`, default seed profile, `created_at`
- [x] `Job` gains a required `project_id`; a job's worktree is created from the project's repo
- [x] Store: `projects` table with `create`, `get`, `list`, `update`, `delete`; deleting a
  project with non-terminal jobs is refused
- [x] Creating a project from a `github_repo` clones it into the state dir when `repo_path`
  is not given
- [x] `POST /projects`, `GET /projects`, `GET /projects/{id}`, `PATCH /projects/{id}`,
  `DELETE /projects/{id}`; `POST /projects/{id}/jobs` replaces `POST /jobs` (old path kept as
  an alias until T7.3)
- [x] CLI: `slipwright project new|list|show`; `slipwright new` takes a project id
- [x] Existing tests still pass with a default project created by the fixtures

### T6.2 — Work breakdown: epics, stories, tasks
**Done when**
- [x] `PlannerResult` gains a `breakdown`: `epics[] → stories[] → tasks[]`, each with id,
  title, description; every task references exactly one plan phase index and every plan
  phase is referenced by exactly one task
- [x] Planner prompt asks for the breakdown; the result schema rejects orphan phases or tasks
- [x] Breakdown is persisted on `Job.data` and returned by `GET /projects/{id}/jobs/{jid}`
- [x] Each task carries a status derived from engine state: `todo`, `in_progress`, `done`,
  `failed` — computed from `phase_index`, build gate result and job state, never stored
  separately
- [x] `GET /projects/{id}/board` merges the breakdowns of all the project's jobs into one
  epic/story/task tree with statuses
- [x] Test: a scripted plan with 2 epics / 3 stories / 4 tasks; drive the job and assert the
  board statuses change task by task

### T6.3 — Progress and activity feed
**Done when**
- [x] `GET /projects/{id}/progress` returns per-job and per-project counts: tasks done /
  total, current state, pending approval, last activity time
- [x] `GET /projects/{id}/activity` returns an itemised, newest-first list built from every
  job's `history` and consumed inbox messages: what happened, which role, when, with a link
  to the transition detail (diff, build log, profile)
- [x] Both endpoints are read-only projections over existing data — no new tables
- [x] Test: after a scripted end-to-end job, the activity feed lists analyst → planner →
  each developer phase → qa stages → devops PR in order

### T6.4 — Test runs on demand
Let the human run the project's tests and read the result without waiting for a build gate.

**Done when**
- [x] `TestRun` model: id, project_id, optional job_id, command, started_at, finished_at,
  exit_code, stdout/stderr (captured to a per-run file, path stored), status
  `running|passed|failed|error`
- [x] `POST /projects/{id}/test-runs` runs `profile.test_cmd` in the project's main checkout;
  with `job_id` it runs in that job's worktree instead. Runs execute as background tasks,
  one at a time per checkout
- [x] `GET /projects/{id}/test-runs`, `GET /test-runs/{id}`, `GET /test-runs/{id}/output`
- [x] Build-gate runs from T3.3 are also recorded as `TestRun`s (source `gate`), so one list
  shows everything that ever ran
- [x] Test: trigger a run against a fixture repo with a failing test, assert exit code and
  output are captured and the run is listed

---

## Phase 7 — Users, settings, API surface

### T7.1 — Users and login
Single-tenant, local users. No external identity provider.

**Done when**
- [x] `users` table: id, username, password hash (scrypt, salted, never plaintext),
  `is_admin`, created_at
- [x] `slipwright user add <name>` creates a user, prompting for the password; the first user
  created is admin
- [x] `POST /auth/login` sets an HttpOnly session cookie; `POST /auth/logout` clears it;
  `GET /auth/me` returns the current user
- [x] Every `/api/*` route except login requires a session or a bearer token
  (`slipwright token new` issues one for the CLI; tokens are stored hashed)
- [x] When no user exists the API answers 503 with a hint to run `slipwright user add`
- [x] Tests: login/logout, wrong password, protected route without session, bearer token

### T7.2 — Settings store and GitHub connection
**Done when**
- [x] `settings` table keyed by name; secrets are encrypted at rest with a key from
  `SLIPWRIGHT_SECRET_KEY` (generated into the state dir on first run if unset)
- [x] GitHub settings: personal access token, default owner/org, default base branch
- [x] `GET /settings/github` never returns the token, only whether one is set and its last
  four characters; `PUT /settings/github` stores it
- [x] `POST /settings/github/test` calls the GitHub API with the stored token and returns the
  authenticated login and rate limit, or a readable error
- [x] `githost.py` passes the stored token to `gh` via `GH_TOKEN` when set; without it the
  existing `gh auth` behaviour is unchanged
- [x] `GET /settings/github/repos` lists repositories the token can see, for the project
  creation form
- [x] Tests use a fake GitHub HTTP server; no test touches the network

### T7.3 — API namespace and live events
**Done when**
- [x] All JSON routes live under `/api/...`; old top-level paths are removed and the CLI is
  updated
- [x] `GET /api/events` is a server-sent-events stream emitting `job.state`, `test_run.state`
  and `activity` events; the engine publishes on every persisted transition
- [x] OpenAPI schema is exported to `schemas/openapi.json` by `scripts/export_schema.py` and a
  test fails if it is stale
- [x] CORS is enabled for the Vite dev origin only when `SLIPWRIGHT_DEV=1`

---

### T7.4 — Jira connection and issue sync
Mirror the work breakdown into Jira so the team sees it where they already work. This task
is the engine-driven baseline (structure and status always land in Jira even if no agent
says a word); T7.5 lets the agents themselves write to Jira on top of it. Jira is a
projection of Slipwright state, never the other way round: the engine does not read Jira to
decide anything.

**Done when**
- [x] Jira settings in the settings store (T7.2): site URL, account e-mail, API token
  (encrypted), default issue type names for epic / story / task
- [x] `GET /settings/jira` never returns the token; `PUT /settings/jira` stores it;
  `POST /settings/jira/test` returns the authenticated account and the projects it can see
- [x] `GET /settings/jira/projects` lists Jira projects for the project creation / edit form;
  a Slipwright project stores `jira_project_key`
- [x] `slipwright/jira.py` client (Jira Cloud REST v3, `httpx`): create issue, set parent,
  transition issue, add comment; tests use a fake Jira HTTP server, no network
- [x] When a plan is approved on a project with a Jira key, every epic / story / task is
  created in Jira with parents set (epic → story → task); issue keys are stored on the
  breakdown items
- [x] Task status changes (T6.2) transition the matching Jira issue (`todo` → `in_progress`
  → `done`); the transition names are configurable per project and an unknown transition is
  logged, not fatal
- [x] On job completion the DevOps PR URL is posted as a comment on every issue the job
  touched; on job failure the failing task gets a comment with the last build output
- [x] Sync is idempotent: re-running a job or re-approving a plan never creates duplicate
  issues (matching on stored keys), and Jira being down never blocks a job — failures are
  recorded in the activity feed and retried on the next transition
- [x] Board rows (T6.2 / T8.3) show the Jira key as a link when synced

---

### T7.5 — Agents act in Jira
Give the roles their own Jira access so they open and progress issues as they work, the way a
developer on the team would. Follows the existing pattern: a role *returns* the actions it
wants, the engine *executes* them after checking permissions (like `FileChange` +
`write_files`). No role ever holds the Jira token.

**Done when**
- [x] New `Permission.JIRA` in the profile schema; the example profile grants it to
  `planner`, `developer`, `qa` and `devops`, not to `analyst`
- [x] Agent credentials are separate from the human's: Jira settings gain an **agent
  account** (e-mail + API token, encrypted) used for everything agents do, so Jira history
  shows the bot, not the person who configured it. Without an agent account the engine
  falls back to the connection from T7.4
- [x] Every role result may carry `jira_actions[]`: `create_issue` (type, summary,
  description, parent), `transition` (issue, to), `comment` (issue, body), `log_work`
  (issue, minutes, note), `link_issues` (from, to, type). Validated by the per-role result
  schema
- [x] The engine executes `jira_actions` only if the role has `Permission.JIRA`; a role
  without it that emits actions gets a typed error back and the actions are dropped and
  logged — never executed silently, never fatal to the job
- [x] Actions are confined to the project's `jira_project_key`; an action naming another
  project is refused and recorded
- [x] Each role's prompt gets a Jira section only when it has the permission: the project
  key, the issue keys of the breakdown items relevant to its current phase (T7.4), and the
  available transitions, so it can address existing issues instead of creating duplicates
- [x] Intended use per role, covered by scripted tests:
  - Planner may create extra sub-tasks it discovers while planning
  - Developer transitions its task to *in progress* when it starts a phase, comments a
    summary of the change and logs work when the build gate passes
  - QA opens `Bug` issues for failures it finds, linked to the story, and closes them when
    the fix passes the gate
  - DevOps comments the PR link and CI result and transitions the story on green CI
- [x] Every executed action is appended to the job's history and the activity feed
  (role, action, issue key, result); every refused one too, with the reason
- [x] Executing the same result twice (restart mid-phase) does not duplicate issues or
  comments: actions carry a client-side idempotency key stored on the job
- [x] Jira outage: actions are queued on `Job.data` and retried on the next transition; the
  job itself never blocks on Jira
- [x] Test: engine-level test with a fake Jira server asserts the full sequence of calls for
  a scripted job, including one refused action from a role without the permission

### T7.6 — Model providers: OpenAI and DeepSeek, keys in settings
Added after Phase 8: let a role run on Anthropic, OpenAI (ChatGPT) or DeepSeek, with API
keys entered in the UI instead of the environment. Invariant 1 still holds: no module
names a model; the settings page lists models by asking each vendor.

**Done when**
- [x] `slipwright/providers/openai_compat.py` speaks the OpenAI chat-completions dialect
  over httpx (JSON mode, `reasoning_effort` where supported, typed errors); DeepSeek is the
  same client with its own base URL and no effort knob (`providers/registry.py`)
- [x] `roles.<role>.provider` in the profile picks the vendor; unset uses the default set
  under Settings → Models; `ModelRequest.provider` carries it; a `RoutingProvider` builds
  vendor clients lazily from settings-or-env credentials (`Engine.provider_credentials`)
- [x] `GET/PUT /api/settings/providers[/{name}]`, `POST …/{name}/test` (lists usable models),
  `GET …/{name}/models`; keys encrypted, never returned, last four shown; admin-only writes
- [x] Web: Settings → Models (key, base URL, test, default, remove) and a provider column
  with model suggestions in every roles table (job profile gate, project Agents page)
- [x] `slipwright serve --provider live` is the default (`anthropic` kept as an alias);
  tests use a fake OpenAI-compatible vendor (`tests/test_providers.py`)

---

## Phase 8 — React web UI

Lives in `web/` (Vite + React + TypeScript, React Router, TanStack Query). `npm run build`
outputs to `slipwright/api/static/`, which FastAPI serves at `/` with an SPA fallback. The UI
talks only to `/api/*` and the SSE stream; it holds no business logic.

### T8.1 — React app skeleton
**Done when**
- [x] `web/` scaffolded with Vite, TypeScript strict, ESLint, Prettier; `npm run build`
  produces `slipwright/api/static/`
- [x] A typed API client is generated from `schemas/openapi.json`; a CI step fails if the
  client is stale
- [x] FastAPI serves the built app with SPA fallback; `slipwright serve` works with and
  without a built `static/` (without it, `/` returns a hint to build)
- [x] Dev mode: `npm run dev` proxies `/api` to the Python server
- [x] Layout shell: sidebar (Projects, Settings), header with current user and logout

### T8.2 — Login and projects list
**Done when**
- [x] `/login` page; unauthenticated visits to any route redirect there and back
- [x] `/projects` lists all projects with: name, repo, jobs running, pending approvals,
  tasks done/total, last activity
- [x] "New project" form: name, description, and either a local path or a GitHub repo
  picked from `GET /settings/github/repos`
- [x] Empty state explains how to add the first project

### T8.3 — Project page: board, progress, developments
**Done when**
- [x] `/projects/:id` with tabs **Overview**, **Board**, **Developments**, **Tests**,
  **Activity**
- [x] Overview: progress bar (tasks done/total), current stage of each running job, pending
  approvals with approve/reject inline
- [x] Board: epic → story → task tree from `GET /projects/{id}/board`, each row with status
  badge, a link to the job and the phase's diff, and the Jira key when synced
- [x] Developments: list of jobs (past and running) and a "New development" form that takes
  the request text and starts a job; the resulting breakdown appears on the board once the
  plan is approved
- [x] Activity: the itemised feed from T6.3, newest first, each item expandable to its
  detail (diff, build log, profile JSON)
- [x] The page updates live from `/api/events`; no manual refresh needed

### T8.4 — Job page: gates, plan, diffs, steering
**Done when**
- [x] `/projects/:id/jobs/:jid` shows the stage stepper (analyzing → … → done) with the
  current state highlighted and approval states marked
- [x] Profile approval: the proposed profile is shown as an editable form; approve or reject
  with feedback
- [x] Plan approval: epics/stories/tasks rendered with each task's goal and changed files;
  approve or reject with feedback
- [x] Test approval: the QA case list is editable (add / remove / edit) and saved via
  `PUT .../tests` before approving
- [x] Per-phase diffs rendered with syntax highlighting; build-gate output shown per attempt
- [x] Steering: send an inbox message; consumed messages show which role consumed them
- [x] Feature parity with the server-rendered dashboard is checked against a written list

### T8.5 — Test results page
**Done when**
- [x] Tests tab lists every `TestRun` (gate and on-demand) with status, duration, command,
  job if any
- [x] "Run tests" button starts a run on the main checkout or on a chosen job's worktree;
  the row appears immediately as `running` and flips via SSE
- [x] Clicking a run shows the full output with the failing section scrolled into view
- [x] Filter by status and by job

### T8.6 — Settings page: GitHub, Jira, agent access and users
**Done when**
- [x] `/settings/github`: token field (write-only, shows "set, ends with …"), default owner,
  base branch, and a "Test connection" button that shows the authenticated login
- [x] `/settings/jira`: site URL, e-mail, token (write-only), issue type names, and a
  "Test connection" button; the project form and project settings let the user pick the
  Jira project and map task statuses to Jira transitions
- [x] `/settings/agents`: per role, a toggle for Jira access (writes `Permission.JIRA`
  into the project's seed profile) and the **agent account** credentials (write-only
  token, "Test connection" shows the bot's Jira login); a warning is shown when agents
  would fall back to the human's token
- [x] Job page (T8.4) and activity feed show each Jira action an agent took, with a link
  to the issue, and each refused action with its reason
- [x] `/settings/users` (admin only): list users, add user, reset password, revoke tokens
- [x] Profile defaults per project editable here or on the project page: per-role model and
  thinking depth, validated against `profile.schema.json` — still no model names in engine
  code

### T8.7 — Retire the server-rendered dashboard
**Done when**
- [x] Every flow in `slipwright/api/ui.py` has a React equivalent (parity list from T8.4
  is fully checked)
- [x] `ui.py` and its tests are deleted; `/` serves the React app
- [x] README documents: build the UI, create the first user, connect GitHub, create a
  project, start a development, approve gates, run tests

### T8.8 — Docker image and compose
Added after Phase 8: run the whole thing locally with one command.

**Done when**
- [x] Multi-stage `Dockerfile`: Node builds the web UI, the runtime image has `git`, `gh`,
  `uv`/Python 3.12 and Node 22 so the DevOps role and the example (Python) profile work
  inside the container; state under `/data`, health check on `/healthz`
- [x] `compose.yaml` with a single service (SQLite needs no database, the event bus no
  queue), a state volume, `./repos` mounted for local checkouts, job ports mapped, provider
  keys and `SLIPWRIGHT_SECRET_KEY` from `.env` (`.env.example`)
- [x] Verified: `docker compose up`, `user add` via `exec`, login, providers page, a
  scripted job reaching the plan gate with its worktree and port inside the container
- [x] README documents the Docker path; `tests/test_docker.py` checks the files stay
  consistent (ports, state dir, volume, ignored paths)

### T8.9 — UI redesign: dashboard, cards, edit/delete flows, theme
Added after Phase 8: the first React pass was a bare skeleton.

**Done when**
- [x] Design tokens (light base, dark under `prefers-color-scheme` or a pinned
  `data-theme`), Inter/JetBrains Mono, icon sidebar with pending-approval count, top bar
  with breadcrumbs and a light/dark/system switch
- [x] `/` is a dashboard: stat tiles (projects, running, waiting, tasks, outcomes), pending
  approvals with inline approve/reject, recent activity across projects
  (`GET /api/overview`, `GET /api/activity`)
- [x] Projects as cards with search, an action menu, edit modal (name, description, GitHub
  repo, Jira key) and a confirm-delete modal; the project page has the same actions
- [x] Developments can be deleted once finished (`DELETE /api/jobs/{id}` removes worktree,
  branch, port and rows; 409 while running), from the table and the job page
- [x] Numbered stepper with connectors, toasts, modals, skeleton loading, empty states,
  status badges with dots; every page checked in both themes with Playwright screenshots

---

## Phase 9 — Specialist agents and a standards knowledge base (RAG)

### Where this sits in the architecture

Slipwright already is an orchestrator in the "restaurant" sense: the engine is the kitchen
manager (state machine + SQLite checkpoints + human gates), roles are the cooks, and
structured outputs (`FileChange`, `jira_actions`) are how a cook uses equipment. Decisions
are mixed on purpose: the skeleton is code (which state runs next, gates, retries), the
Planner is the one LLM decision that shapes the work. Phase 9 keeps that and adds two
things: **specialist cooks** (analysis, backend, web UI, mobile UI, tester, devops) and a
**shared cookbook** every cook is handed the right page of before they start — the
standards, retrieved per task (RAG) rather than pasted whole into every prompt.

Design decisions, made up front so tasks do not re-litigate them:

- **Specialists are roles, not new pipelines.** The pipeline stays analyst → planner →
  develop → build gate → QA → DevOps. The Planner tags every phase with a `domain`
  (`backend`, `web`, `mobile`, `infra`, `docs`, `general`) and the engine invokes the
  matching specialist for that phase. Model, thinking depth, provider and permissions per
  specialist come from the profile (invariant 1 untouched). `developer` remains the
  generic fallback for `general`/unknown domains so existing profiles keep working.
- **The people at the table are a product team.** `po` (Product Owner) turns the request
  into epics, stories and tasks — the backlog — and that is what goes into Jira.
  `architect` reads the backlog and the repository and answers "how": the project
  profile (build / test / run), architecture decisions, and domain-tagged phases, each
  implementing exactly one task. Specialists build, `qa` proposes test cases and writes
  unit, integration and end-to-end tests, `devops` ships. The old `analyst` and
  `planner` roles are folded into `architect` and `po` (T9.0).
- **Two review points before code.** `backlog` → *backlog approval* (the PO's tree, which
  is also mirrored to Jira on approval) → `architecture` → *architecture approval*
  (profile + decisions + phases). Rejecting re-runs the same agent with feedback.
- **Standards live in Markdown under version control** (`standards/<domain>/*.md` in this
  repo, plus optional per-project overrides in `<repo>/.slipwright/standards/`). Editing
  in the UI writes those files; the index is derived, never the source of truth.
- **Retrieval storage stays in SQLite** for v1: a `standards_chunks` table with an FTS5
  index (keyword/BM25, zero dependencies, works offline) plus an optional embedding blob
  for semantic search. Embeddings come from a pluggable `Embedder`: `openai`
  (`text-embedding-3-small`, uses the stored OpenAI key), `local` (sentence-transformers,
  e.g. `BAAI/bge-m3`, an optional extra because the model is ~2 GB and slows the Docker
  image), or `none` (FTS5 only). Hybrid ranking when both exist. Chroma/pgvector/Qdrant
  can replace the store later behind the same `StandardsIndex` interface; they are not
  needed to start.
- **Core rules never depend on retrieval.** `standards/core.md` (security, secrets, no
  destructive git, licensing) is always in the prompt; RAG adds the domain pages.
- **Retrieval is traceable.** Every role invocation records which chunks it was given, so
  a wrong page can be found and the corpus fixed.
- **Sequential per job.** Phases of one job still run one after another in one worktree;
  parallelism stays at the job level (several developments at once). Parallel phases in
  one job would need sub-worktrees and a merge step — a later phase, if ever.
- **Mobile toolchains are a profile concern.** The mobile specialist writes code like any
  other; whether `build_cmd` can run Flutter/React Native depends on the project's profile
  and the machine/image running Slipwright (the default image ships Python and Node only).

### T9.0 — Role model: PO, Architect, QA (two new gates)
Requested after T9.3: replace analysis with a Product Owner, add a Software Architect,
make QA own end-to-end tests.

**Done when**
- [x] `RoleName`: `po`, `architect`, `developer`, `backend`, `web_ui`, `mobile_ui`, `qa`,
  `devops`, `supervisor`; `analyst` and `planner` are gone from code, profiles, prompts,
  standards and the UI
- [x] States: `created → backlog → awaiting_backlog_approval → architecture →
  awaiting_architecture_approval → developing → build_gate → qa → awaiting_test_approval
  → devops → done | failed`; illegal transitions still raise; resume works from every
  state; rejection at either new gate re-runs that agent with the feedback (bounded)
- [x] `POResult`: summary + breakdown (epics → stories → tasks, no phases yet);
  `ArchitectResult`: summary + profile + `decisions[]` + phases, each with a `domain` and a
  `task_id`; the engine checks every task has exactly one phase and writes the phase
  numbers back into the breakdown so the board, Jira sync and agent Jira context keep
  working unchanged
- [x] Jira mirroring starts at backlog approval (tasks `todo`), statuses move as phases
  complete; the human may edit the proposed profile at the architecture gate
  (`PUT /api/jobs/{id}/profile`)
- [x] QA instructions cover end-to-end tests (Playwright / the project's e2e runner) in
  addition to unit and integration tests; standards gain `product` and `architecture`
  domains (the `analysis` pages move under `product`)
- [x] Web: stepper, gate panels (backlog tree; profile + decisions + phases), agent cards
  and labels reflect the new roles and states
- [x] Tests updated: Phase 2–5 role tests now target PO and Architect; every later suite
  passes against the new states

> Design note for T9.0: `slipwright/roles/po.py` and `roles/architect.py` replace
> `analyst.py` / `planner.py`. The PO runs first with the seed profile only; `job.profile`
> stays `None` until the Architect proposes one (`accepted_profile` keeps the seed's `roles`).
> `job.data.backlog` is the PO's tree; `job.data.plan` is the Architect's
> `{summary, decisions, phases, breakdown}` where `architect.phase_task_map` has checked the
> 1:1 task↔phase mapping and written `task.phase`. Jira mirroring moved to backlog approval
> (`_jira_reconcile` sees `backlog` when `plan` is absent), so the Architect already sees
> issue keys in its Jira context. `activity.py` derives role prefixes generically
> (`"<role>:"`, `"<role> phase"`), so new roles need no changes there. Tests describe plans
> through `tests.pipeline.set_plan(provider, seed, phases)`, which scripts a matching PO
> backlog (`t1..tN`) and Architect reply. `tests/test_po_architect.py` replaces
> `test_analyst.py`.

### T9.1 — Specialist agents: backend, web UI, mobile UI
**Done when**
- [x] `RoleName` gains `backend`, `web_ui`, `mobile_ui`; `Profile.roles` requires them;
  the example profile and `schemas/profile.schema.json` are updated; `developer` stays as
  the generic fallback
- [x] `PlanPhase.domain` (`backend|web|mobile|infra|docs|general`) is required from the
  Planner; breakdown tasks show it; the board and job page show a domain badge per task
- [x] The engine's develop step dispatches by domain: `backend`→`backend`, `web`→`web_ui`,
  `mobile`→`mobile_ui`, `infra`→`devops`, everything else →`developer`; CI-fix rounds use
  the same specialist that wrote the phase
- [x] Each specialist has its own instructions file (`slipwright/roles/specialists/*.py`)
  stating scope and hand-off rules (a web change that needs a new endpoint goes back to the
  Planner as a new phase, never done by the web agent)
- [x] `/agents` shows the six agents as **cards** (Analysis, Backend, Web UI, Mobile UI,
  Tester, DevOps): icon, one-line scope, provider + model, thinking depth, permissions as
  chips, Jira on/off, number of standards sections, last used; the sidebar gets an
  "Agents" entry and Settings → Agents becomes this page
- [x] Clicking a card opens the agent's detail page `/agents/<role>` with tabs
  **Setup** (per project: provider, model, thinking depth, permissions — the roles table
  reduced to one row), **Standards** (T9.6: the domain's pages, editable) and
  **Activity** (recent invocations across projects with prompt size and standards used)
- [x] Tests: a scripted plan with phases in three domains asserts the requests went to the
  three specialists with exactly the profile's model for each (extends T5.2's routing test)

### T9.2 — Standards corpus
**Done when**
- [x] `standards/` in this repo: `core.md` (always-on rules) and one folder per domain —
  `analysis/`, `backend/`, `web/`, `mobile/`, `testing/`, `devops/` — each file with
  front-matter (`domain`, `tags`, `applies_to` languages/frameworks) and `##` sections that
  each cover one topic (the chunking unit)
- [x] Initial content written for every domain (coding conventions, error handling,
  logging, API design, state management, accessibility, test pyramid, CI/CD, secrets,
  observability) — concrete enough that a retrieved section answers "how do we do X here"
- [x] `<repo>/.slipwright/standards/` in a project overrides or extends the global corpus
  (same layout); project pages take precedence on ties
- [x] A linter (`scripts/check_standards.py`, run in tests) rejects files without
  front-matter, sections over 400 words, or duplicate headings within a domain

### T9.3 — Standards index (RAG)
**Done when**
- [x] `slipwright/standards/`: `chunker` (split by `##`, keep the file title and domain in
  every chunk), `Embedder` protocol with `openai`, `local` (optional extra
  `uv sync --extra local-embeddings`) and `none` implementations, `StandardsIndex` over
  SQLite (`standards_chunks` + FTS5 virtual table + embedding blob)
- [x] `search(query, domain, k=4)` returns ranked chunks with scores and source
  (file, heading); hybrid rank = FTS5 BM25 merged with cosine when embeddings exist;
  project chunks outrank global ones on equal score
- [x] `slipwright standards reindex [--project <id>]` and automatic reindex on server
  start and when a project's `.slipwright/standards/` changes (mtime check); indexing is
  incremental by content hash so unchanged chunks are not re-embedded
- [x] Settings store the embedder choice (`standards.embedder`); OpenAI embeddings use the
  key from Settings → Models
- [x] Tests use a deterministic fake embedder: "Kafka consumer yaz" retrieves the retry
  policy section; a `web` query never returns backend chunks; reindex after editing a file
  replaces only that file's chunks

### T9.4 — Retrieval into every role's prompt
**Done when**
- [x] `base_context` gains a `standards` section: `core` (full `core.md`) plus `retrieved`
  chunks for the role's domain, chosen by a query built from the request, the current
  phase goal, its files and the breakdown task title; capped by a token budget per role
  (default 2 000 tokens, profile-configurable)
- [x] Role → domain mapping: po→product, architect→architecture plus every other domain
  (k=2 each), specialists→their domain, qa→testing, devops→devops; the Architect also
  receives the list of domains so it can tag phases
- [x] Every invocation records the chunk ids and headings it was given as a history entry
  (`standards: 3 section(s) for backend`) and in `RoleResult.usage`-style metadata; the
  job page lists them per phase
- [x] Prompts tell the role that retrieved standards are binding unless they contradict
  `core`, and to say so in `summary` when a standard could not be followed
- [x] Tests: the developer prompt for a Kafka phase contains the retry section and not the
  accessibility section; the token budget truncates deterministically

> Design note for T9.4: `slipwright/standards/retrieval.py`. `Engine._invoke` calls
> `standards_for(job, role, profile)` unless the caller passed `standards=`; the result's
> `as_context()` (`note`, `domain`, `core`, `retrieved[]`) goes into `base_context`. The
> query leads with the phase goal, files and backlog task title (FTS keeps only the first
> 32 tokens), the request last. Budget: `RoleConfig.standards_budget`, else the
> `token_budget` standards setting (2 000); sections are taken in rank order, one that does
> not fit is dropped and smaller ones after it may still be taken; `estimate_tokens` is
> len/4 so the cut is provider-independent. When nothing in the role's own domain matches,
> `StandardsIndex.browse` supplies the domain's opening sections (a PO always reads how
> backlogs are written). Each call records `standards (<role>[ phase N]): K section(s)` in
> the history *before* the role runs (so `history[-1]` after a phase is still the role's
> transition); `ActivityKind.STANDARDS`, and the job page lists them under the phase card.
> `RoleResult.standards` carries the chunk ids.

### T9.5 — Standards review gate
**Done when**
- [x] After each specialist phase passes the build gate, a `review` step asks the QA
  role to check the phase diff against the retrieved standards and return
  `violations[]` (section, file, line, severity, fix hint); `none` passes
- [x] `blocking` violations send the phase back to the same specialist with the list
  (max 2 rounds, then the job waits at a new `awaiting_review_approval` gate where the
  human can accept or reject); `advisory` ones are recorded and shown, never block
- [x] The review step is per project configurable (`review: off|advisory|blocking`) in the
  project's edit dialog (and on creation through the API) and defaults to `advisory`
- [x] Violations appear on the job page (per phase) and on the board (task badge); Jira
  gets a comment on the task when blocking violations were found (through T7.4's sync)
- [x] Tests: scripted violations trigger exactly two fix rounds and then the gate; an
  advisory project never blocks

> Design note for T9.5: new states `review` / `awaiting_review_approval` between the build
> gate and the next phase (`_build_gate` → `REVIEW` unless the mode is `off`).
> `slipwright/roles/review.py` runs QA with review instructions; `QAResult.violations`
> (`Violation`: section, file, line, severity, message, fix) is the output. The reviewer
> receives the *specialist's* retrieval (`standards_for(job, specialist, profile)`), never
> QA's testing domain, and the phase diff from `job.data.phase_base_commit` (HEAD when the
> phase first started) to HEAD, so fix rounds are reviewed as a whole. Blocking mode: the
> phase index steps back, the specialist gets `standards_review` (violations, round,
> feedback) and the `REVIEW_FIX` instructions, the build gate commits again (`review fix N`
> in the note) — two rounds (`Engine.max_review_rounds`), then the gate. Approve keeps the
> phase; reject steps the phase back with the feedback and resets the rounds. Records live
> in `job.data.reviews` (the board reads `latest_reviews` for the task badge; Jira gets a
> one-shot comment per blocking record via `jira_marks` `review:<phase>:<round>`).
> `Engine(review=...)` forces a mode (older tests use `off`); otherwise `Project.review`.
> Pipeline: the phase card stays running while the review is open and a
> `review_gate:<n>` card appears when the human is asked.

### T9.6 — Standards in the UI
The standards are reached **through the agent**: each agent card's *Standards* tab is the
editor for that agent's domain, so "what does the Backend agent follow?" is one click.

**Done when**
- [x] Agent detail → Standards tab: the domain's pages as a list with search, page count
  and last edit; **New page** (title + Markdown), edit in a Markdown editor with preview,
  delete with confirmation; a *Scope* switch chooses the global corpus or a project's
  override; save writes the file and triggers an incremental reindex
- [x] `core.md` is shown on every agent's Standards tab as a read-only "applies to all"
  block with a link to edit it (admin only)
- [x] "Try a search" box: enter a task sentence, pick a domain, see the ranked chunks with
  scores — the tool for tuning headings and chunking
- [x] Embedder settings (none / openai / local) with a status line (chunks indexed, last
  reindex, model) and a *Reindex now* button
- [x] Job page: per phase, the standards sections that were given to the agent and any
  review violations; project page Overview shows review health (advisory/blocking counts)
- [x] Git: files edited in the UI are committed on a `slipwright/standards` branch of this
  repo (or the project repo for overrides) so changes are reviewable

> Design note for T9.6: `slipwright/standards/editing.py` (`StandardsEditor`) owns page
> CRUD: paths are checked against `<domain>/<name>.md` | `core.md`, a save is linted in a
> temp dir together with its siblings (duplicate headings, section length, front-matter)
> and refused with a 422 before anything is written, then written where the agents read
> it (`standards/` or `<repo>/.slipwright/standards`) and `ensure_standards_indexed`
> reindexes (the corpus fingerprint now uses `st_mtime_ns`). The review branch: a
> worktree of the same repository under `<state>/standards-branches/` checked out on
> `slipwright/standards`; the edited file is copied there and committed, so the running
> checkout never changes branch; no git → no branch, logged. API: `/api/standards/pages`
> (list/create), `/api/standards/pages/{path}` (get/put/delete, admin for writes),
> `project_id` selects a project's overrides. Web: `pages/AgentStandardsTab.tsx` (scope
> switch, page table, `PageEditor` modal with Markdown/preview tabs, `NewPageModal`,
> `CoreBlock`, `TrySearch` over `/api/settings/standards/search`, `IndexSettings` with
> reindex); a small `Markdown` renderer avoids a dependency. `ProjectProgress` gained
> `reviews` / `review_blocking` / `review_advisory` for the Overview tab.

### T9.7 — Orchestrator hardening: budgets, retries, supervisor decisions
**Done when**
- [x] Per-job budget: max total tokens, max wall-clock, max invocations (profile or
  project settings); exceeding one fails the job with a readable reason, never silently
- [x] Per-role retry policy for provider errors (timeouts, 5xx, malformed JSON):
  exponential backoff, bounded attempts, all recorded in history
- [x] Loop detection: the same (role, phase, output hash) twice in a row stops the loop and
  routes to a gate instead of a third identical attempt
- [x] One explicit LLM decision point where code cannot decide: on a failed build gate the
  supervisor role chooses between "same specialist fixes", "re-plan this phase"
  or "ask the human", returning JSON; the choice and its reason are recorded
- [x] Context hygiene: each role receives only what its instructions list (no full plan
  dumps into the Tester, no diffs into the Planner); prompt sizes are measured and shown
  on the job page per invocation
- [x] Tests cover budget exhaustion, retry-then-success, loop detection and each
  supervisor branch with the scripted provider

> Design note for T9.7: everything hangs off `Engine._invoke`. Budget: `Project.budget`
> (`BudgetSettings`: max_tokens / max_wall_clock_s / max_invocations, None = unlimited) is
> checked before every call; a breach returns an `InvokeErrorKind.BUDGET` result and
> `_invocation_failed` fails the job with `budget exhausted: <reason>`. Accounting lives in
> `job.data.invocations`, `tokens_used` and `invocation_log[]` (role, state, phase,
> attempts, prompt_chars, tokens, ok/error) — the job page's "Model calls" table.
> Retries: `RoleConfig.retries` (default 2) for `RETRYABLE` kinds (timeout, provider
> error, malformed output; refusals and missing providers are not), backoff
> `retry_backoff_s · 2^(attempt-1)` (engine default 2 s, tests 0), each failed attempt a
> history entry. Loop check: `_output_key` = role:phase_index:state:review_round for
> producing roles (judges — the reviewer and the supervisor — are exempt); the same output
> hash twice in a row returns `InvokeErrorKind.LOOP` and `_ask_human` moves the job to the
> new `awaiting_decision` gate with `job.data.resume_state`; approve resumes that state,
> reject resumes it with the feedback queued in the inbox; any human decision resets the
> hashes. Failed build gate: `_failed_gate_choice` asks the supervisor (unless the project
> is `manual`) — `fix` (as before), `replan` (feedback + `ARCHITECTURE`, phase index reset;
> `BUILD_GATE → ARCHITECTURE` is now legal) or `ask_human` (decision gate); the choice is a
> history entry. Context hygiene: `plan_outline()` gives specialists and QA the summary,
> decisions and phase goals only; the architect never sees diffs; `RoleResult.prompt_chars`
> is measured in `invoke_role`.

### T9.8 — Supervisor at the gates: manual / assisted / auto
The gates stay in the state machine (invariant 2); what changes is who calls *approve*.

**Done when**
- [x] A `supervisor` role (model/provider from the profile like every role) is invoked when
  a job reaches a gate and returns `{decision: approve|reject, confidence, risk:
  low|medium|high, reasons[], feedback}` after reading the same material the human sees
  (profile / plan + standards / test cases / written tests) plus the relevant standards
- [x] Gate mode per project (project edit dialog, `Project.supervisor`): `manual` — no
  supervisor; `assisted` (default) — the recommendation, confidence and reasons are shown
  on the gate panel and the dashboard, the human decides; `auto` — the supervisor approves
  when `decision=approve`, `risk=low` and confidence ≥ a threshold, otherwise the gate
  waits for the human; rejections are never automatic
- [x] Every automatic approval is a normal `approve` call recorded as
  `approved by supervisor (confidence 0.92): <reasons>`; the human can still reject
  afterwards while the next phase runs (the inbox carries the feedback), and can switch
  the project back to `manual` at any time
- [x] A per-job cap on automatic approvals (default 3) and a hard rule: the final
  DevOps/PR gate is never auto-approved unless the project explicitly allows it
- [x] Dashboard: "approved by supervisor" items are listed separately with an *Undo*
  (reject with feedback) action; notifications (toast over SSE + optional webhook under Settings → notifications) on every
  automatic approval
- [x] Tests: assisted mode never changes state; auto mode approves a low-risk plan and
  stops at a high-risk one; the cap and the DevOps rule hold; a supervisor error falls
  back to manual

> Design note for T9.8: `slipwright/roles/supervisor.py` builds the gate material the
> human sees (`material(job)`: backlog / profile+plan / last review / test cases / the
> branch diff for written tests) and the recent history; `Engine._supervise` runs after
> every handler that lands on a gate (inside `_run`, so an automatic approval simply lets
> the loop continue). `Project.supervisor` = `SupervisorSettings(mode, threshold, cap,
> allow_final_gate)`; `Engine(supervisor_mode=...)` forces a mode for tests
> (`tests/pipeline.full_engine` defaults to manual). The record lives in
> `job.data.supervision` (`acted`: none | auto | error, `blockers[]` in auto mode) and
> as a history entry `supervisor: recommends …`; an automatic approval is
> `Engine.approve(by="supervisor (confidence x): reasons")` → note `approved by supervisor
> (…)`, `job.data.auto_approvals` counts against the cap, the final gate (written tests,
> `qa_stage == 2`) is refused unless `allow_final_gate`. `undo_auto_approval` marks the
> record undone and queues an inbox message for the next role (`POST /api/jobs/{id}/undo`).
> An SSE event `supervisor.auto_approved` drives the toast (`useLiveEvents(_, onNotice)`)
> and `_notify_webhook` POSTs to `notifications.webhook_url`. Pipeline cards carry
> `recommendation` / `confidence` / `risk` / `auto_approved`; `JobProgress` and
> `Overview.auto_approved` feed the dashboard's Undo list. The pipeline "Select all
> recommended" button closes T9.9's last item.

### T9.9 — Project pipeline view and bulk approvals
Inside a project, every development is a row of **step cards** (Backlog → Backlog gate →
Architecture → Architecture gate → Backend/Web/Mobile phases → QA → Test gates → DevOps →
Done), each card showing its state; what waits for the human is actionable in place and
in bulk.

**Done when**
- [x] Project page gets a **Pipeline** tab (and it becomes the default tab): one lane per
  development, step cards coloured by state (pending / running with a pulse / done /
  failed / waiting for you), the agent's name on each card, elapsed time, and the phase
  cards expanded per domain (a Backend card, a Web UI card, …) with the task title
- [x] Clicking a card opens a side panel with that step's output (profile, plan, diff,
  gate log, test cases, PR) — the same material the job page shows, without leaving the
  lane
- [x] Cards waiting for approval carry a **checkbox**; a sticky action bar shows
  "N selected" with **Approve selected** and **Reject selected…** (one feedback text
  applied to all); selection can span several developments; each approval is an ordinary
  gate call recorded per job
- [x] Editable gates edit in place: the profile form, the plan/breakdown (reorder phases,
  rename tasks, change a task's domain), and the test-case list open in the side panel;
  **Save & approve** sends the edited version and continues, **Save** only stores it
- [x] Supervisor recommendations (T9.8, assisted mode) appear on the waiting cards as a
  chip (recommends approve · 0.92) so bulk approval can follow them with one click
  ("Select all recommended")
- [x] The dashboard's pending list gains the same checkboxes and bulk bar
- [x] Live: cards move as SSE events arrive; a bulk approval of three gates shows three
  lanes advancing without a refresh
- [x] `PUT /api/jobs/{id}/plan` (edit the proposed plan/breakdown while awaiting the
  architecture approval, validated like the Architect's output) and `PUT /api/jobs/{id}/backlog` and `POST /api/jobs/approve` /
  `POST /api/jobs/reject` for batches (`job_ids[]`, per-job result) back the UI
- [x] Tests: batch endpoints approve the eligible jobs and report the rest (409 per job,
  not for the batch); plan edits are validated (orphan phases rejected); UI source checks

> Design note for T9.9: `slipwright/pipeline.py` derives every lane from the job's state
> and history alone (`lane_for`), so the view is exact after a restart. Working steps take
> their latest visit to a state and the transition that left it as the output; gates take
> the approval after their last visit; QA's two passes are split at the first approval of
> the test gate (`_Reader.qa_spans`). Phase cards come from `plan.phases` (one per task,
> specialist label + domain + task title) and collect the `<role> phase i/n` and build-gate
> records. `GET /api/projects/{id}/pipeline` returns `Pipeline{lanes[], waiting}`; every
> card lists the history indexes of its outputs, which the side panel fetches through the
> existing `/history/{index}` endpoint. Edits: `Engine.set_backlog` / `set_plan` reuse the
> PO / Architect validators (`Breakdown`, `PlanPhase`, `phase_task_map`) and raise
> `InvalidEdit` → 422. Batches: `POST /api/jobs/approve|reject` iterate `Engine.approve` /
> `reject` per job and report `{job_id, ok, state|error}` (a job not at a gate is an entry,
> never a batch failure). Web: `pages/PipelineTab.tsx` (lanes, `StepCardView`, `StepPanel`
> with `GateEditor` + `SaveRow`), `components/GateEditors.tsx` (backlog tree, phase
> reorder/domain/rename, test cases), `components/BulkBar.tsx` (shared with the dashboard).
> Selection is derived from the live lanes, so a job that moves on drops out by itself.
> The supervisor chip waits for T9.8.

### Follow-ups after Phase 9 (user feedback)

- [x] **Default provider drives the agents.** Settings → Models has a *Default model* per
  provider (picked from the vendor's `/models` list); every role without a pinned provider
  runs on the default provider *and* its default model (`RoutingProvider.route`,
  `Engine.effective_routing`); agent cards show the effective provider/model.
- [x] **Generic Developer removed.** `general`/`docs` phases go to the Backend agent;
  `RETIRED_ROLES` (`analyst`, `planner`, `tester`, `developer`) are ignored when an older
  profile is loaded.
- [x] **Jira agent account and project mapping** moved from the Agents page to Settings →
  Jira.
- [x] **Local checkout picker.** `SLIPWRIGHT_LOCAL_REPOS` (compose sets `/repos`) is listed
  by `GET /api/local-repos`; the New project form offers the folders (non-git ones
  disabled) instead of asking for a path blind.

- [x] **Fail → Retry.** `POST /api/jobs/{id}/retry` (`Engine.retry`) continues a failed job
  from the working state it failed in (build/CI/review counters reset, optional note to the
  next role via the inbox); Retry buttons on the job page and the pipeline lane; the failed
  callout shows the transition that failed, not the bookkeeping after it.
- [x] **Output too long → work in parts.** `ProviderTruncatedError` /
  `InvokeErrorKind.TRUNCATED`: the specialist is asked once more for a smaller part
  (`output_was_truncated`), and `phase_complete=false` makes `_develop` call it again with
  `continuation` (files so far) up to `max_phase_parts` (4) before the build gate. Output
  limits per vendor in `ProviderSpec.max_tokens` (32k; DeepSeek 8k).
- [x] **Server env never leaks into project commands.** `gates.project_env()` strips
  `VIRTUAL_ENV` / `UV_PROJECT_ENVIRONMENT` / `PYTHONPATH` (a project's `uv sync` wiped the
  container's venv once); the Dockerfile sets `UV_PROJECT_ENVIRONMENT` only while building.
- [x] **Jira issue types resolved against the project.** `JiraSync._resolve_types` reads
  createmeta once per sync and swaps a name that cannot nest (a level-0 `Task` under a
  story) for the project's sub-task type, noting it in the history.
- [x] Pipeline lanes wrap into a grid instead of scrolling sideways.

- [x] **Sprints.** After the backlog is mirrored, stories join the project's active sprint,
  or (`Project.jira_sprint = create`, the default) a two-week sprint named after the
  development is created and started; sub-tasks follow their parents. `JiraClient`
  gained the Agile calls (`board_id`, `active_sprint`, `create_sprint`, `add_to_sprint`).
- [x] **Truncation escalates.** Up to three smaller-part retries (`TRUNCATION_STEPS`: a few
  files → exactly one file → one minimal file); per-provider **Max output tokens** override
  under Settings → Models (`Credentials.max_tokens`), vendor defaults in `ProviderSpec`.

- [x] **The PO's round.** `Engine.jira_sweep()` reconciles every development of a
  Jira-linked project (missing issues, sprint, statuses) under the job's lock; the API runs
  it 5 s after startup and then every `jira_sweep_s` (3600); `GET/POST
  /api/settings/jira/sweep` show and trigger it; the Jira page has the card.

## Phase 10 — Proposed (not started)

### T10.1 — Parallel phases per domain
Today the phases of one development run one after another in a single worktree (a phase
commits, the next builds on it). Backend, web and mobile phases are often independent once
the architecture is approved.

**Done when**
- [ ] The Architect marks each phase with `depends_on` (phase numbers); phases with no
  unmet dependency are *ready* together
- [ ] Ready phases of different domains run concurrently, each in its own worktree and
  branch off the same base (`jobs never share checkouts` holds per worker); each passes
  its own build gate and standards review
- [ ] Finished branches are merged back in dependency order; a merge conflict is handed to
  the specialist that owns the later phase with the conflict shown, then to the human
  (decision gate) if it stays; QA runs on the merged branch as today
- [ ] The pipeline lane shows concurrent phases side by side with their own status; Jira
  statuses follow each task
- [ ] Concurrency cap per project (default 3) and per-role model budgets still apply
- [ ] Tests: two independent phases run at once (scripted provider with a barrier), a
  dependent phase waits, a conflicting merge reaches the specialist and then the gate

### Definition of done for Phase 9

- [x] A request touching backend and web is planned into domain-tagged phases, each phase
  is implemented by its specialist with that specialist's model, and every specialist
  prompt contains the relevant standards sections (verified by an end-to-end scripted test)
- [x] Editing a standard in the UI changes what the next invocation retrieves, with no
  restart
- [x] A phase violating a blocking standard is fixed by the specialist or stopped at the
  review gate; nothing ships past it without a human
- [x] In `auto` mode a low-risk development reaches the PR with the human only reading
  notifications; in `manual` mode nothing moves without a click
- [x] From the project's Pipeline tab a human can see every step of every development,
  edit a plan in place and approve three waiting gates with one action
- [x] All Phase 0–8 invariants hold; no module names a model

> Verified by: `tests/test_phase9_retrieval.py` (backend + web phases, specialists, Kafka /
> accessibility sections), `test_phase9_editing.py` (edit → next retrieval, no restart),
> `test_phase9_review.py` (blocking findings: two fix rounds, then the gate),
> `test_phase9_supervisor.py` (auto with the final gate allowed reaches DONE; manual never
> asks), `test_phase9_pipeline.py` (plan edit in place, batch approval of three gates) and
> `test_agent_invocation.py` (no model names in engine code).

---

## Definition of done for Phases 6–8

- [x] A new user can, from the browser alone: log in, connect GitHub, create a project from
  a GitHub repo, type a request, approve the profile and plan, watch the board fill in task
  by task, run the tests, read the results, and see the PR link — with no CLI use
  (`tests/test_phase8_e2e.py::test_a_new_user_ships_a_change_from_the_browser_alone`)
- [x] Two developments on the same project run concurrently and the board shows both
  (`tests/test_phase8_e2e.py::test_two_developments_run_concurrently_and_share_the_board`,
  isolation proven in `tests/test_phase5.py`)
- [x] With Jira connected, the same flow produces the epic / story / task tree in Jira and
  the issues move to done as the tasks complete
  (`tests/test_phase7_jira.py::test_plan_approval_mirrors_the_breakdown_and_tracks_status`)
- [x] With an agent account configured, Jira history shows the agents' own comments,
  transitions and bug issues under the bot account, and nothing under the human's
  (`tests/test_phase7_agents.py::test_agents_act_in_jira_through_the_engine`)
- [x] Every Phase 0–5 invariant still holds; the Phase 0–5 suite changed only in URL
  prefixes (`/api`), `require_auth=False` in app fixtures, and the removal of the T5.3
  dashboard test whose flows moved to the React app (`web/PARITY.md`)

---

## Definition of done for the whole build

- [x] Two jobs run concurrently against the same repo, end to end, without interference
  (`tests/test_phase5.py::test_two_jobs_run_concurrently_end_to_end_without_interference`)
- [x] Killing the server at any phase and restarting resumes every in-flight job
  (`test_restart_at_every_phase_resumes_the_job`, parametrised over every working state)
- [x] No engine module references a model name
  (`tests/test_agent_invocation.py::test_engine_has_no_hardcoded_model_names`)
- [x] A job cannot advance past any approval state without an explicit approve call
  (`test_approval_states_never_advance_without_approve`)
