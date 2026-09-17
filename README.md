# Slipwright

A multi-agent SDLC harness. Analyst, Planner, Developer, QA and DevOps agents run each
job in its own git worktree, with human approval gates between phases.

See [TASKS.md](TASKS.md) for the build plan and design notes.

## How a job flows

```
created ─▶ analyzing ─▶ awaiting_profile_approval ─▶ planning ─▶ awaiting_plan_approval
                                                                        │
        ┌───────────────────────────────────────────────────────────────┘
        ▼
   developing ─▶ build_gate ─▶ (next phase … ) ─▶ qa ─▶ awaiting_test_approval ─▶ qa
                                                                                   │
                     done ◀─ devops ◀─ awaiting_test_approval ◀────────────────────┘
```

- **Analyst** reads the worktree and proposes the project profile (language, build /
  test / run commands, port). You approve or reject it with feedback.
- **Planner** produces ordered phases. You approve or reject (max 3 re-runs).
- **Developer** implements one phase per invocation. After each phase the **build gate**
  runs the profile's `build_cmd` and `test_cmd`; failures go back to the Developer
  (max 3 attempts), each green phase is committed on the job branch.
- **QA** first proposes test cases (editable before approval), then writes tests for the
  approved list; the new tests pass the same build gate before you approve them.
- **DevOps** pushes the branch, opens a pull request described from the plan and the
  job history, polls CI, and feeds red CI back to the Developer (max 3 fixes).

Every transition is persisted to SQLite before the next phase runs. Kill the server at
any point and restart it: in-flight jobs resume, jobs waiting on you keep waiting.

## Getting started

```sh
uv sync                                  # Python side
cd web && npm install && npm run build   # web UI -> slipwright/api/static/
cd ..
uv run slipwright user add ada           # first login (prompted for a password; becomes admin)
uv run slipwright serve                  # http://127.0.0.1:8500
```

Then, in the browser:

1. **Log in** with the user you just created.
2. **Settings → GitHub**: paste a personal access token and click *Test connection*. The
   token clones private repositories, pushes job branches and opens pull requests. It is
   stored encrypted (key in `SLIPWRIGHT_SECRET_KEY` or `<state>/secret.key`).
3. **Settings → Jira** (optional): site URL, e-mail and API token. Approved plans are then
   mirrored as epics → stories → sub-tasks, issues move as tasks complete, PR links and
   failures are commented. **Settings → Agents** holds the separate bot account the agents
   act as, and per project which roles may act in Jira (the `jira` permission), which
   model and thinking depth each role uses, the Jira project and its transition names.
4. **Projects → New project**: pick a GitHub repository (or a local path) and, if you use
   Jira, the Jira project.
5. On the project page, **Developments → New development**: describe what you want.
6. **Approve the gates** as they come — the Analyst's profile (editable), the Planner's
   epics/stories/tasks, QA's test cases (editable), the written tests. Pending approvals
   are also shown on the project overview and on the projects list.
7. Watch the **Board** fill in task by task, read every diff and build log under the job's
   **Phases** and **History**, and steer a running job with a message.
8. **Tests**: run the project's test command on the main checkout or in a job's worktree
   and read the output; every build gate the engine ran is listed there too.
9. When the job is done, the **PR link** is on the job page and in the activity feed.

Every transition is persisted to SQLite before the next phase runs. Kill the server at
any point and restart it: in-flight jobs resume, jobs waiting on you keep waiting.

### CLI

Client commands talk to the API with a bearer token (`slipwright token new <user>` prints
one; pass it as `--token` or `SLIPWRIGHT_TOKEN`).

```sh
uv run slipwright project new demo --github octocat/demo --jira DEM
uv run slipwright project list
uv run slipwright new <project-id> "add a /health endpoint"
uv run slipwright status                # or: slipwright status <job-id>
uv run slipwright approve <job-id>      # leave the current gate
uv run slipwright reject <job-id> "use poetry, not pip"
uv run slipwright message <job-id> "keep the public API unchanged"
```

The JSON API is documented at `/docs`; `GET /api/events` streams server-sent events for
every change. `slipwright serve --no-auth` skips login for trusted local use.

### Configuration

Settings come from the environment (or `serve` flags):

| Variable | Default | Meaning |
|---|---|---|
| `SLIPWRIGHT_STATE_DIR` | `.slipwright` | SQLite file, secret key, worktrees, clones, test logs |
| `SLIPWRIGHT_PROFILE` | `examples/python-fastapi.profile.json` | default seed profile (see below) |
| `SLIPWRIGHT_PROVIDER` | `anthropic` | `anthropic` or `scripted` (offline, canned replies) |
| `SLIPWRIGHT_PORT` | `8500` | API port |
| `SLIPWRIGHT_PORT_RANGE` | `8100-8999` | ports handed to jobs' live environments |
| `SLIPWRIGHT_AUTH` | `1` | set to `0` to serve without login |
| `SLIPWRIGHT_SECRET_KEY` | generated into the state dir | Fernet key for stored tokens |
| `SLIPWRIGHT_DEV` | `0` | allow the Vite dev server origin (CORS) |

The Anthropic provider reads credentials the way the SDK does (`ANTHROPIC_API_KEY`, or
an `ant auth login` profile). DevOps pushes and opens pull requests through the `gh` CLI,
using the stored GitHub token when one is set.

## Tuning model and thinking depth per role

Every job starts from a **seed profile**. The Analyst may rewrite the project facts in it,
but the `roles` map is always taken from the seed: which model plays which role is a human
decision, never a model's. Engine code never names a model — a test greps for it.

```json
"roles": {
  "analyst":   { "model": "claude-sonnet-5", "thinking_depth": "medium", "permissions": ["read_files", "run_commands"] },
  "planner":   { "model": "claude-opus-5",   "thinking_depth": "high",   "permissions": ["read_files"] },
  "developer": { "model": "claude-opus-5",   "thinking_depth": "high",   "permissions": ["read_files", "write_files", "run_commands"] },
  "qa":        { "model": "claude-sonnet-5", "thinking_depth": "medium", "permissions": ["read_files", "write_files", "run_commands"] },
  "devops":    { "model": "claude-haiku-4-5", "thinking_depth": "low",   "permissions": ["read_files", "run_commands", "network", "git_push"] }
}
```

- `model` is passed to the provider verbatim. Change it, restart `serve` (or point a new
  job at a different `--profile`), and that role runs on the new model — no code changes.
- `thinking_depth` is one of `off`, `low`, `medium`, `high`, `max`. On the Anthropic
  provider `off` disables thinking; the others enable adaptive thinking and set
  `output_config.effort` to the same word. Use `low` for cheap mechanical roles (DevOps),
  `high` where correctness matters (Planner, Developer).
- `permissions` are enforced by the engine, not by prompts: a Developer without
  `write_files` cannot change the worktree, a DevOps role without `git_push` cannot open
  a PR.

Provider-specific caveat: models that only support fixed thinking budgets (e.g. Haiku 4.5)
reject `effort`; give such roles `thinking_depth: "off"` or route them to a model that
supports adaptive thinking.

To verify routing, `tests/test_phase5.py::test_each_role_uses_exactly_the_model_named_in_the_profile`
runs a whole job and asserts every request carried the profile's model for its role.

Projects can carry their own seed profile (Settings → Agents), which is what the web UI
edits; jobs of a project without one start from `SLIPWRIGHT_PROFILE`.

## Development

```sh
uv run pytest
uv run ruff check .
uv run mypy
uv run python scripts/export_schema.py   # after changing models or routes
cd web && npm run gen:api && npm run lint && npm run typecheck && npm run build
```

`schemas/openapi.json` and the generated TypeScript client (`web/src/api/schema.d.ts`) are
committed; tests fail when either is stale. `npm run dev` in `web/` serves the UI with
hot reload and proxies `/api` to a `slipwright serve` started with `SLIPWRIGHT_DEV=1`.

`SLIPWRIGHT_PROVIDER=scripted uv run slipwright serve --no-auth` drives the full pipeline
with canned model replies, useful for exercising the UI and the CLI without a network.
