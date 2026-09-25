# Working on Slipwright

Orientation for an agent picking this repository up. [README.md](README.md) explains what
Slipwright *does*; this says how it is built, what the rules are, and which mistakes have
already been made so they are not made again.

## What it is, in one paragraph

A multi-agent SDLC harness. A person writes a request; a Product Owner turns it into a
backlog, an Architect into a plan, specialists build it one phase at a time, QA writes
tests, DevOps opens the pull request. A human approves at every gate. The agents do not
talk to each other: a deterministic state machine (`slipwright/engine.py`) calls one role
at a time, each answering with a typed JSON schema (`slipwright/roles/results.py`), and
every transition is persisted before the next one runs.

## Two deployments, one codebase

This is the single most important thing to hold in mind, because almost every design
decision below follows from it.

| | **Local** | **Hosted** |
|---|---|---|
| Who writes the build commands | you | strangers |
| Database | SQLite file | PostgreSQL |
| Commands run | on the machine | in a throwaway container |
| Model keys | the installation's | each account's own |
| Quotas | off | on |

Neither is a special case of the other, and **nothing that protects the hosted mode is on
by default**: a person upgrading a local install must not find their work suddenly
refused. `SLIPWRIGHT_RUNNER`, the quotas and `SLIPWRIGHT_DATABASE_URL` are all opt-in,
and the server logs a warning at startup when it accepts signups with no quotas set.

## Layout

```
slipwright/
  engine.py           the state machine: every phase, gate and retry. Large; the choke
                      point for anything that runs a role
  orchestrator/       which transitions are legal
  roles/              one module per agent + results.py, the typed output contract
  invoke.py           the single place a model is called
  providers/          Anthropic, OpenAI and five OpenAI-compatible vendors; registry.py
                      routes per role
  gates/              build_cmd and test_cmd: env.py (what they may see),
                      runner.py (where they run)
  standards/          the RAG corpus: chunking, retrieval, fts.py (the one dialect split)
  store/              persistence. schema.py declares every table; db.py owns the engine
  api/                FastAPI. __init__.py is projects and jobs, settings.py is settings,
                      auth.py is accounts
  alembic/            migrations, in order

  accounts.py         signing up, proving an address, resetting a password
  mail.py             SMTP, and the outbox that stands in for it
  demo.py             the worked example a new account starts with
  quota.py            what one account may take of a shared machine
  teams.py            the people an account puts on its agents
  translate.py        agent prose in the language it was not written in
  brief/discovery     what a project *is*, before any development starts
  worklist.py         what a development will do, grouped by agent
  steps.py            what one pipeline step actually produced
  costs.py + prices.py  what a development cost against what it was expected to
  support.py          the support desk
  net.py              retrying a request that never left

web/src/              React. i18n.tsx translates the interface, i18n/said.tsx the agents'
                      own prose
```

## The rules that are easy to break

**Ownership.** `Project` and `Job` carry `owner_id`. Every store read takes an optional
`owner_id` and a row belonging to somebody else is **not found**, never forbidden -- a
403 confirms that an id exists. In the API, `_owner(request)` and the funnel helpers
(`_get`, `_get_project`, `_get_run`) apply it; use them rather than touching the store
directly from an endpoint.

**Whose keys.** A job runs on *its owner's* credentials -- model provider, Git token and
Jira alike. `Engine.for_user(id)` returns the same engine bound to one account; the run
path resolves it from `job.owner_id`. Do not add a settings read that bypasses it. Which
settings are personal and which are the installation's is decided in exactly one place:
`store/scoped.py`.

**The event bus filters at the source.** `Event.owner_id` decides delivery and is
excluded from the SSE payload. The `project_id` query parameter on `/api/events` is a
reader's convenience, **not** an authorisation check -- it was once mistaken for one.

**A project's own commands are hostile input.** `build_cmd` and `test_cmd` are written by
a model. Their environment is an **allow list** (`gates/env.py`): name a variable or it
is not there. Worktrees live outside the state directory so nothing can reach
`secret.key` by relative path. Never widen either without saying why.

**Both dialects.** Queries are SQLAlchemy Core against `store/schema.py` and must run on
SQLite and PostgreSQL. The only sanctioned divergence is keyword search, in
`standards/fts.py`. Anything else that needs raw SQL probably wants rethinking.

**Agent prose is translated, interface text is not.** `useT()` looks up English source
strings in `web/src/i18n/tr.ts`. `useSay()` looks up what an *agent* wrote, through the
server's translation bridge. Read-only agent text gets `say()`; an editable field does
not, because what you type there is saved and shipped to Jira in the project's language.
A person's own request and feedback are never translated.

## Running it

```bash
uv run pytest -q                       # ~6 min, SQLite
uv run ruff check . && uv run mypy     # lint and types
cd web && npm run build                # the server serves web/dist from slipwright/api/static
uv run python scripts/export_schema.py # after any API model change
cd web && node scripts/gen-api.mjs     # then regenerate the TypeScript client
```

The web UI is **built, not served from source**: a change is invisible until
`npm run build` has run. `schemas/openapi.json` is committed and a test fails when it is
stale.

### Against PostgreSQL

```bash
docker run -d --name pg -e POSTGRES_PASSWORD=slipwright -e POSTGRES_USER=slipwright \
    -e POSTGRES_DB=slipwright -p 55432:5432 postgres:16-alpine
SLIPWRIGHT_TEST_DATABASE_URL=postgresql+psycopg://slipwright:slipwright@127.0.0.1:55432/slipwright \
    uv run pytest -q
```

That runs the **whole** suite on PostgreSQL, not a subset: the `store` fixture swaps the
database and empties the schema per test. It is slower (~12 min) and worth it -- it is
what caught a GIN index that never built, a half-created database that could never be
opened again, and an image with no driver in it.

## Configuration

| Variable | Default | What it decides |
|---|---|---|
| `SLIPWRIGHT_DATABASE_URL` | SQLite under the state dir | PostgreSQL for a hosted install |
| `SLIPWRIGHT_STATE_DIR` | `.slipwright` | database, `secret.key` |
| `SLIPWRIGHT_WORK_DIR` | `<state>-work` | checkouts. **Never inside the state dir** |
| `SLIPWRIGHT_RUNNER` | `local` | `docker` for a container per command |
| `SLIPWRIGHT_QUOTA_MAX_*` | `0` (off) | running jobs, projects, disk |
| `SLIPWRIGHT_DEMO_PROJECT` | on | the worked example a new account starts with |
| `SLIPWRIGHT_SECRET_KEY` | generated in the state dir | encrypts stored credentials. **Required** with PostgreSQL |

## How to write here

Match the surrounding code: it is unusually heavily commented, and the comments explain
*why*, not what. A comment that restates the line below it is noise; one that records the
reason a thing is the way it is, or the failure that shaped it, is the point.

Tests are named as sentences about behaviour (`test_a_job_is_run_on_its_owners_keys`) and
assert on what a person would notice, not on internals. When a test breaks because
behaviour deliberately changed, rewrite it to state the new rule -- do not weaken it.

## Traps

- **`_may_act` guards the gates.** Approve, reject and the gate editors go through it. It
  also refuses the demo project. A new mutating endpoint that skips it has no guard.
- **The demo project has no checkout.** Anything that would run something in it must
  refuse (409) rather than fail deeper in. Deleting it is allowed -- that is its purpose.
- **`_resume_all` is deliberately unscoped.** The server starting is not somebody asking;
  in-flight work of every account must carry on, each on its own owner's credentials.
- **Alembic is quiet on purpose.** It narrates at INFO, which once landed in a CLI's
  stdout and corrupted a token it printed. `store/migrate.py` sets it to WARNING.
- **A new database is created and stamped in one transaction.** Both engines run DDL
  transactionally; without that, a half-built database came back with tables but no
  revision and could never be migrated.
- **`Permission.RUN_COMMANDS` and `NETWORK` were declared for a long time and never
  checked.** The first is enforced now. If you add a permission, enforce it in the same
  commit or do not add it.
- **Positional assertions rot.** A test that asserted on `provider_settings()[2]` broke
  the day a vendor was added. Look things up by name.

## Gates, in order

More than the README's diagram shows, because gates were added after it was drawn. A
development stops for a person at each of these, and `_may_act` guards every one:

| Gate | What is being approved | Who may |
|---|---|---|
| backlog | epics, stories and tasks | owner, or the Product Owner's member |
| architecture | the profile, the stack, the decisions, the phases | owner, or the Architect's member |
| design | the screens the Designer drew | owner, or the Designer's member |
| review | blocking standards findings, after two fix rounds | owner |
| test cases | what QA proposes to test | owner, or QA's member |
| written tests | the tests themselves, once green | owner, or QA's member |
| deployment | where and how it is deployed | owner |

A stopped development has three ways out and they are different: **retry** (the same step
again), **replan** (back to the backlog with a note about what to try instead) and
**re-run** (one finished step again, on the work that is already there). Those are the
owner's, never a member's.

## Where things are written down

- **[README.md](README.md)** — what Slipwright is and how to run it. For people.
- **[TASKS.md](TASKS.md)** — the build plan, phase by phase, with the design notes for
  each. The long-form *why* for decisions that predate this file.
- **This file** — orientation and the rules that are easy to break.
- **The code** — comments carry the reasoning. When something here and a comment
  disagree, the comment is nearer the truth; fix this file.
