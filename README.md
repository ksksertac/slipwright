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

## Running it

```sh
uv sync
uv run slipwright serve                 # API + dashboard on http://127.0.0.1:8500
uv run slipwright new /path/to/repo "add a /health endpoint"
uv run slipwright status                # or: slipwright status <job-id>
uv run slipwright approve <job-id>      # leave the current gate
uv run slipwright reject <job-id> "use poetry, not pip"
uv run slipwright message <job-id> "keep the public API unchanged"
```

The dashboard at `/` lists jobs, their current phase and pending approvals; approve,
reject, edit test cases and send steering messages from the page. `/ui/jobs/<id>` shows
the full history with every diff and build log. The JSON API lives at `/jobs` (see
`/docs`).

Settings come from the environment (or `serve` flags):

| Variable | Default | Meaning |
|---|---|---|
| `SLIPWRIGHT_STATE_DIR` | `.slipwright` | SQLite file and worktrees |
| `SLIPWRIGHT_PROFILE` | `examples/python-fastapi.profile.json` | seed profile (see below) |
| `SLIPWRIGHT_PROVIDER` | `anthropic` | `anthropic` or `scripted` (offline, canned replies) |
| `SLIPWRIGHT_PORT` | `8500` | API port |
| `SLIPWRIGHT_PORT_RANGE` | `8100-8999` | ports handed to jobs' live environments |

The Anthropic provider reads credentials the way the SDK does (`ANTHROPIC_API_KEY`, or
an `ant auth login` profile). DevOps uses the `gh` CLI for pushing and pull requests.

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

## Development

```sh
uv run pytest
uv run ruff check .
uv run mypy
```

`SLIPWRIGHT_PROVIDER=scripted uv run slipwright serve` drives the full pipeline with
canned model replies, useful for exercising the dashboard and the CLI without a network.
