# Slipwright

A multi-agent SDLC harness. Product Owner, Architect, Developer (backend / web UI /
mobile UI specialists), QA and DevOps agents run each job in its own git worktree, with
human approval gates between phases.

See [TASKS.md](TASKS.md) for the build plan and design notes.

## How a job flows

```
created ─▶ backlog ─▶ awaiting_backlog_approval ─▶ architecture ─▶ awaiting_architecture_approval
                                                                                  │
        ┌─────────────────────────────────────────────────────────────────────────┘
        ▼
   developing ─▶ build_gate ─▶ (next phase … ) ─▶ qa ─▶ awaiting_test_approval ─▶ qa
                                                                                   │
                     done ◀─ devops ◀─ awaiting_test_approval ◀────────────────────┘
```

- **Product Owner** reads the request and the worktree and writes the backlog: epics,
  stories and tasks. You approve or reject it with feedback (max 3 re-runs); on approval
  the tree is mirrored to Jira when the project has one.
- **Architect** designs from the approved backlog: the project profile (language, build /
  test / run commands, port), the architectural decisions and one ordered phase per task,
  each tagged with a domain. You edit the profile and approve, or reject with feedback.
- **Developer** implements one phase per invocation — the backend, web UI or mobile UI
  specialist when the phase's domain has one. After each phase the **build gate**
  runs the profile's `build_cmd` and `test_cmd`; failures go back to the Developer
  (max 3 attempts), each green phase is committed on the job branch.
- **QA** first proposes test cases (editable before approval), then writes unit and
  end-to-end tests for the approved list; the new tests pass the same build gate before
  you approve them.
- **DevOps** pushes the branch, opens a pull request described from the plan and the
  job history, polls CI, and feeds red CI back to the Developer (max 3 fixes).

Every transition is persisted to SQLite before the next phase runs. Kill the server at
any point and restart it: in-flight jobs resume, jobs waiting on you keep waiting.

## Getting started

### With Docker (recommended for a local install)

Everything Slipwright needs — the API, the web UI, `git`, `gh`, `uv`/Python and Node for
the projects it works on — is in one image; state (SQLite, secret key, clones, worktrees,
test logs) lives in the `slipwright-state` volume. There is no database or queue to run
alongside it.

```sh
cp .env.example .env                    # optional: API keys, a stable SLIPWRIGHT_SECRET_KEY
docker compose up --build -d            # http://localhost:8500
docker compose exec slipwright slipwright user add ada   # first login (admin)
```

- Local checkouts: the folder named by `SLIPWRIGHT_REPOS` in `.env` (default `./repos/`)
  is mounted at `/repos` inside the container, so a checkout at `<that folder>/myapp` is
  registered with `repo_path = /repos/myapp`. GitHub repositories are cloned into the volume.
- Jobs' live environments use ports `8100–8130` (mapped through; change
  `SLIPWRIGHT_PORT_RANGE` and the port mapping in `compose.yaml` together).
- Projects whose `run_cmd`/`build_cmd` call Docker need the socket mount that is commented
  out in `compose.yaml`.
- `SLIPWRIGHT_PROVIDER=scripted docker compose up` runs the whole pipeline with canned
  model replies, no keys needed.

### From source

```sh
uv sync                                  # Python side
cd web && npm install && npm run build   # web UI -> slipwright/api/static/
cd ..
uv run slipwright user add ada           # first login (prompted for a password; becomes admin)
uv run slipwright serve                  # http://127.0.0.1:8500
```

Then, in the browser:

1. **Log in** with the user you just created.
2. **Settings → Models**: paste API keys for the providers you want to use — Anthropic
   (Claude), OpenAI (ChatGPT) or DeepSeek — and click *Test connection* to see the models
   each key can use. Keys are stored encrypted; a key in the server's environment
   (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) is used when none is stored.
   Which provider and model each role runs on is set per project under **Agents**.
3. **Settings → GitHub**: paste a personal access token and click *Test connection*. The
   token clones private repositories, pushes job branches and opens pull requests. It is
   stored encrypted (key in `SLIPWRIGHT_SECRET_KEY` or `<state>/secret.key`).
4. **Settings → Jira** (optional): site URL, e-mail and API token. Approved plans are then
   mirrored as epics → stories → sub-tasks, issues move as tasks complete, PR links and
   failures are commented. **Settings → Agents** holds the separate bot account the agents
   act as, and per project which roles may act in Jira (the `jira` permission), which
   model and thinking depth each role uses, the Jira project and its transition names.
5. **Projects → New project**: pick a GitHub repository (or a local path) and, if you use
   Jira, the Jira project.
6. On the project page, **Developments → New development**: describe what you want.
7. **Approve the gates** as they come — the Product Owner's epics/stories/tasks, the
   Architect's profile (editable) and phases, QA's test cases (editable), the written
   tests. Pending approvals
   are also shown on the project overview and on the projects list.
8. Watch the **Board** fill in task by task, read every diff and build log under the job's
   **Phases** and **History**, and steer a running job with a message.
9. **Tests**: run the project's test command on the main checkout or in a job's worktree
   and read the output; every build gate the engine ran is listed there too.
10. When the job is done, the **PR link** is on the job page and in the activity feed.

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
| `SLIPWRIGHT_PROVIDER` | `live` | `live` (route per role to Anthropic / OpenAI / DeepSeek) or `scripted` (offline, canned replies) |
| `SLIPWRIGHT_PORT` | `8500` | API port |
| `SLIPWRIGHT_PORT_RANGE` | `8100-8999` | ports handed to jobs' live environments |
| `SLIPWRIGHT_AUTH` | `1` | set to `0` to serve without login |
| `SLIPWRIGHT_SECRET_KEY` | generated into the state dir | Fernet key for stored tokens |
| `SLIPWRIGHT_DEV` | `0` | allow the Vite dev server origin (CORS) |

Model provider keys come from Settings → Models or the environment variables above.
DevOps pushes and opens pull requests through the `gh` CLI,
using the stored GitHub token when one is set.

## Tuning model and thinking depth per role

Every job starts from a **seed profile**. The Architect may rewrite the project facts in it,
but the `roles` map is always taken from the seed: which model plays which role is a human
decision, never a model's. Engine code never names a model — a test greps for it.

```json
"roles": {
  "po":        { "model": "claude-sonnet-5", "thinking_depth": "medium", "permissions": ["read_files", "jira"] },
  "architect": { "model": "claude-opus-5",   "thinking_depth": "high",   "permissions": ["read_files", "run_commands", "jira"] },
  "developer": { "model": "claude-opus-5",   "thinking_depth": "high",   "permissions": ["read_files", "write_files", "run_commands"] },
  "backend":   { "model": "claude-opus-5",   "thinking_depth": "high",   "permissions": ["read_files", "write_files", "run_commands"] },
  "web_ui":    { "model": "claude-opus-5",   "thinking_depth": "high",   "permissions": ["read_files", "write_files", "run_commands"] },
  "mobile_ui": { "model": "claude-opus-5",   "thinking_depth": "high",   "permissions": ["read_files", "write_files", "run_commands"] },
  "qa":        { "model": "claude-sonnet-5", "thinking_depth": "medium", "permissions": ["read_files", "write_files", "run_commands"] },
  "devops":    { "model": "claude-haiku-4-5", "thinking_depth": "low",   "permissions": ["read_files", "run_commands", "network", "git_push"] }
}
```

- `provider` picks the vendor for the role: `anthropic`, `openai` or `deepseek` (unset =
  the default chosen under Settings → Models). OpenAI and DeepSeek are driven through the
  OpenAI-compatible chat-completions API; `thinking_depth` becomes `reasoning_effort`
  where the vendor supports it (OpenAI) and is ignored where it does not (DeepSeek).
- `model` is passed to the provider verbatim. Change it (Settings → Agents, or the seed
  profile file) and that role runs on the new model — no code changes, no restart.
- `thinking_depth` is one of `off`, `low`, `medium`, `high`, `max`. On the Anthropic
  provider `off` disables thinking; the others enable adaptive thinking and set
  `output_config.effort` to the same word. Use `low` for cheap mechanical roles (DevOps),
  `high` where correctness matters (Architect, Developer).
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
