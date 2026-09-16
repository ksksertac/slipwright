# Slipwright

A multi-agent SDLC harness. Analyst, Planner, Developer, QA and DevOps agents run each
job in its own git worktree, with human approval gates between phases.

See [TASKS.md](TASKS.md) for the build plan.

## Development

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```
