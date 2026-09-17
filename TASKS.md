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
- React 18 + Vite + TypeScript for the web UI (`web/`), built to static files served by FastAPI

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

> **Resume here:** Phases 0–6 and T7.1 are complete. Next task is **T7.2 — Settings store and GitHub connection**.
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
| 5 | T5.3 Job dashboard | [x] |
| 6 | T6.1 Project entity | [x] |
| 6 | T6.2 Work breakdown: epics, stories, tasks | [x] |
| 6 | T6.3 Progress and activity feed | [x] |
| 6 | T6.4 Test runs on demand | [x] |
| 7 | T7.1 Users and login | [x] |
| 7 | T7.2 Settings store and GitHub connection | [ ] |
| 7 | T7.3 API namespace and live events | [ ] |
| 7 | T7.4 Jira connection and issue sync | [ ] |
| 7 | T7.5 Agents act in Jira | [ ] |
| 8 | T8.1 React app skeleton | [ ] |
| 8 | T8.2 Login and projects list | [ ] |
| 8 | T8.3 Project page: board, progress, developments | [ ] |
| 8 | T8.4 Job page: gates, plan, diffs, steering | [ ] |
| 8 | T8.5 Test results page | [ ] |
| 8 | T8.6 Settings page: GitHub, Jira, agent access and users | [ ] |
| 8 | T8.7 Retire the server-rendered dashboard | [ ] |

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
- [ ] `settings` table keyed by name; secrets are encrypted at rest with a key from
  `SLIPWRIGHT_SECRET_KEY` (generated into the state dir on first run if unset)
- [ ] GitHub settings: personal access token, default owner/org, default base branch
- [ ] `GET /settings/github` never returns the token, only whether one is set and its last
  four characters; `PUT /settings/github` stores it
- [ ] `POST /settings/github/test` calls the GitHub API with the stored token and returns the
  authenticated login and rate limit, or a readable error
- [ ] `githost.py` passes the stored token to `gh` via `GH_TOKEN` when set; without it the
  existing `gh auth` behaviour is unchanged
- [ ] `GET /settings/github/repos` lists repositories the token can see, for the project
  creation form
- [ ] Tests use a fake GitHub HTTP server; no test touches the network

### T7.3 — API namespace and live events
**Done when**
- [ ] All JSON routes live under `/api/...`; old top-level paths are removed and the CLI is
  updated
- [ ] `GET /api/events` is a server-sent-events stream emitting `job.state`, `test_run.state`
  and `activity` events; the engine publishes on every persisted transition
- [ ] OpenAPI schema is exported to `schemas/openapi.json` by `scripts/export_schema.py` and a
  test fails if it is stale
- [ ] CORS is enabled for the Vite dev origin only when `SLIPWRIGHT_DEV=1`

---

### T7.4 — Jira connection and issue sync
Mirror the work breakdown into Jira so the team sees it where they already work. This task
is the engine-driven baseline (structure and status always land in Jira even if no agent
says a word); T7.5 lets the agents themselves write to Jira on top of it. Jira is a
projection of Slipwright state, never the other way round: the engine does not read Jira to
decide anything.

**Done when**
- [ ] Jira settings in the settings store (T7.2): site URL, account e-mail, API token
  (encrypted), default issue type names for epic / story / task
- [ ] `GET /settings/jira` never returns the token; `PUT /settings/jira` stores it;
  `POST /settings/jira/test` returns the authenticated account and the projects it can see
- [ ] `GET /settings/jira/projects` lists Jira projects for the project creation / edit form;
  a Slipwright project stores `jira_project_key`
- [ ] `slipwright/jira.py` client (Jira Cloud REST v3, `httpx`): create issue, set parent,
  transition issue, add comment; tests use a fake Jira HTTP server, no network
- [ ] When a plan is approved on a project with a Jira key, every epic / story / task is
  created in Jira with parents set (epic → story → task); issue keys are stored on the
  breakdown items
- [ ] Task status changes (T6.2) transition the matching Jira issue (`todo` → `in_progress`
  → `done`); the transition names are configurable per project and an unknown transition is
  logged, not fatal
- [ ] On job completion the DevOps PR URL is posted as a comment on every issue the job
  touched; on job failure the failing task gets a comment with the last build output
- [ ] Sync is idempotent: re-running a job or re-approving a plan never creates duplicate
  issues (matching on stored keys), and Jira being down never blocks a job — failures are
  recorded in the activity feed and retried on the next transition
- [ ] Board rows (T6.2 / T8.3) show the Jira key as a link when synced

---

### T7.5 — Agents act in Jira
Give the roles their own Jira access so they open and progress issues as they work, the way a
developer on the team would. Follows the existing pattern: a role *returns* the actions it
wants, the engine *executes* them after checking permissions (like `FileChange` +
`write_files`). No role ever holds the Jira token.

**Done when**
- [ ] New `Permission.JIRA` in the profile schema; the example profile grants it to
  `planner`, `developer`, `qa` and `devops`, not to `analyst`
- [ ] Agent credentials are separate from the human's: Jira settings gain an **agent
  account** (e-mail + API token, encrypted) used for everything agents do, so Jira history
  shows the bot, not the person who configured it. Without an agent account the engine
  falls back to the connection from T7.4
- [ ] Every role result may carry `jira_actions[]`: `create_issue` (type, summary,
  description, parent), `transition` (issue, to), `comment` (issue, body), `log_work`
  (issue, minutes, note), `link_issues` (from, to, type). Validated by the per-role result
  schema
- [ ] The engine executes `jira_actions` only if the role has `Permission.JIRA`; a role
  without it that emits actions gets a typed error back and the actions are dropped and
  logged — never executed silently, never fatal to the job
- [ ] Actions are confined to the project's `jira_project_key`; an action naming another
  project is refused and recorded
- [ ] Each role's prompt gets a Jira section only when it has the permission: the project
  key, the issue keys of the breakdown items relevant to its current phase (T7.4), and the
  available transitions, so it can address existing issues instead of creating duplicates
- [ ] Intended use per role, covered by scripted tests:
  - Planner may create extra sub-tasks it discovers while planning
  - Developer transitions its task to *in progress* when it starts a phase, comments a
    summary of the change and logs work when the build gate passes
  - QA opens `Bug` issues for failures it finds, linked to the story, and closes them when
    the fix passes the gate
  - DevOps comments the PR link and CI result and transitions the story on green CI
- [ ] Every executed action is appended to the job's history and the activity feed
  (role, action, issue key, result); every refused one too, with the reason
- [ ] Executing the same result twice (restart mid-phase) does not duplicate issues or
  comments: actions carry a client-side idempotency key stored on the job
- [ ] Jira outage: actions are queued on `Job.data` and retried on the next transition; the
  job itself never blocks on Jira
- [ ] Test: engine-level test with a fake Jira server asserts the full sequence of calls for
  a scripted job, including one refused action from a role without the permission

---

## Phase 8 — React web UI

Lives in `web/` (Vite + React + TypeScript, React Router, TanStack Query). `npm run build`
outputs to `slipwright/api/static/`, which FastAPI serves at `/` with an SPA fallback. The UI
talks only to `/api/*` and the SSE stream; it holds no business logic.

### T8.1 — React app skeleton
**Done when**
- [ ] `web/` scaffolded with Vite, TypeScript strict, ESLint, Prettier; `npm run build`
  produces `slipwright/api/static/`
- [ ] A typed API client is generated from `schemas/openapi.json`; a CI step fails if the
  client is stale
- [ ] FastAPI serves the built app with SPA fallback; `slipwright serve` works with and
  without a built `static/` (without it, `/` returns a hint to build)
- [ ] Dev mode: `npm run dev` proxies `/api` to the Python server
- [ ] Layout shell: sidebar (Projects, Settings), header with current user and logout

### T8.2 — Login and projects list
**Done when**
- [ ] `/login` page; unauthenticated visits to any route redirect there and back
- [ ] `/projects` lists all projects with: name, repo, jobs running, pending approvals,
  tasks done/total, last activity
- [ ] "New project" form: name, description, and either a local path or a GitHub repo
  picked from `GET /settings/github/repos`
- [ ] Empty state explains how to add the first project

### T8.3 — Project page: board, progress, developments
**Done when**
- [ ] `/projects/:id` with tabs **Overview**, **Board**, **Developments**, **Tests**,
  **Activity**
- [ ] Overview: progress bar (tasks done/total), current stage of each running job, pending
  approvals with approve/reject inline
- [ ] Board: epic → story → task tree from `GET /projects/{id}/board`, each row with status
  badge, a link to the job and the phase's diff, and the Jira key when synced
- [ ] Developments: list of jobs (past and running) and a "New development" form that takes
  the request text and starts a job; the resulting breakdown appears on the board once the
  plan is approved
- [ ] Activity: the itemised feed from T6.3, newest first, each item expandable to its
  detail (diff, build log, profile JSON)
- [ ] The page updates live from `/api/events`; no manual refresh needed

### T8.4 — Job page: gates, plan, diffs, steering
**Done when**
- [ ] `/projects/:id/jobs/:jid` shows the stage stepper (analyzing → … → done) with the
  current state highlighted and approval states marked
- [ ] Profile approval: the proposed profile is shown as an editable form; approve or reject
  with feedback
- [ ] Plan approval: epics/stories/tasks rendered with each task's goal and changed files;
  approve or reject with feedback
- [ ] Test approval: the QA case list is editable (add / remove / edit) and saved via
  `PUT .../tests` before approving
- [ ] Per-phase diffs rendered with syntax highlighting; build-gate output shown per attempt
- [ ] Steering: send an inbox message; consumed messages show which role consumed them
- [ ] Feature parity with the server-rendered dashboard is checked against a written list

### T8.5 — Test results page
**Done when**
- [ ] Tests tab lists every `TestRun` (gate and on-demand) with status, duration, command,
  job if any
- [ ] "Run tests" button starts a run on the main checkout or on a chosen job's worktree;
  the row appears immediately as `running` and flips via SSE
- [ ] Clicking a run shows the full output with the failing section scrolled into view
- [ ] Filter by status and by job

### T8.6 — Settings page: GitHub, Jira, agent access and users
**Done when**
- [ ] `/settings/github`: token field (write-only, shows "set, ends with …"), default owner,
  base branch, and a "Test connection" button that shows the authenticated login
- [ ] `/settings/jira`: site URL, e-mail, token (write-only), issue type names, and a
  "Test connection" button; the project form and project settings let the user pick the
  Jira project and map task statuses to Jira transitions
- [ ] `/settings/agents`: per role, a toggle for Jira access (writes `Permission.JIRA`
  into the project's seed profile) and the **agent account** credentials (write-only
  token, "Test connection" shows the bot's Jira login); a warning is shown when agents
  would fall back to the human's token
- [ ] Job page (T8.4) and activity feed show each Jira action an agent took, with a link
  to the issue, and each refused action with its reason
- [ ] `/settings/users` (admin only): list users, add user, reset password, revoke tokens
- [ ] Profile defaults per project editable here or on the project page: per-role model and
  thinking depth, validated against `profile.schema.json` — still no model names in engine
  code

### T8.7 — Retire the server-rendered dashboard
**Done when**
- [ ] Every flow in `slipwright/api/ui.py` has a React equivalent (parity list from T8.4
  is fully checked)
- [ ] `ui.py` and its tests are deleted; `/` serves the React app
- [ ] README documents: build the UI, create the first user, connect GitHub, create a
  project, start a development, approve gates, run tests

---

## Definition of done for Phases 6–8

- [ ] A new user can, from the browser alone: log in, connect GitHub, create a project from
  a GitHub repo, type a request, approve the profile and plan, watch the board fill in task
  by task, run the tests, read the results, and see the PR link — with no CLI use
- [ ] Two developments on the same project run concurrently and the board shows both
- [ ] With Jira connected, the same flow produces the epic / story / task tree in Jira and
  the issues move to done as the tasks complete
- [ ] With an agent account configured, Jira history shows the agents' own comments,
  transitions and bug issues under the bot account, and nothing under the human's
- [ ] Every Phase 0–5 invariant still holds and the Phase 0–5 test suite is untouched

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
