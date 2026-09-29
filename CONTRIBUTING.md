# Contributing

Thank you for looking. This is a young project and the best contributions right now are
small and concrete: a bug you hit, a message that read badly, a provider that behaves
differently from the others.

Start with [CLAUDE.md](CLAUDE.md). It is written for an agent picking the repository up,
which makes it the fastest orientation a person can get too: what the pieces are, which
rules are easy to break, and which mistakes have already been made.

## Getting it running

```bash
uv sync                    # Python 3.12
uv run pytest -q           # ~7 minutes, SQLite, no API key needed
cd web && npm ci && npm run build
uv run slipwright serve    # http://localhost:8500
```

You do not need a model key to work on most of this. `SLIPWRIGHT_PROVIDER=scripted` runs
the whole pipeline against canned answers, which is how the tests drive it and how the
demo is recorded.

## Before you open a pull request

```bash
uv run ruff check . && uv run mypy      # both must be clean
uv run pytest -q
cd web && npx tsc -b && npm run build   # the UI is built, not served from source
```

Two things that catch people out:

- **The web UI is built.** A change to `web/src` is invisible until `npm run build` has
  run; the server serves `slipwright/api/static`.
- **`schemas/openapi.json` is committed.** After any API model change, run
  `uv run python scripts/export_schema.py` and then `cd web && node scripts/gen-api.mjs`.
  A test fails when it is stale.

## How to write here

Match the surrounding code. It is unusually heavily commented, and the comments explain
*why* rather than what — the reason a thing is the way it is, or the failure that shaped
it. A comment that restates the line below it is noise.

Tests are named as sentences about behaviour (`test_a_job_is_run_on_its_owners_keys`) and
assert on what a person would notice rather than on internals. When a test breaks because
behaviour deliberately changed, rewrite it to state the new rule — do not weaken it.

## What is worth doing

Issues tagged **good first issue** are small, self-contained, and have somewhere obvious
to put the test. If you want something larger, [TASKS.md](TASKS.md) is the long-form
record of how this was built and what was deliberately left for later.

If you are adding a model provider: they live in `slipwright/providers/`, and all but
Anthropic speak the OpenAI protocol against their own host, so a new vendor is usually a
row in `registry.py` plus a test.

## Reporting something

For a bug, the job's **Model calls** tab and the transition that entered `failed` carry
almost everything needed — say what you expected, what happened, and which provider you
were on. If it involves a model's answer, the answer itself matters more than the
traceback.

Please do not open a public issue for a security problem. Mail the address in the repo's
About instead.
