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
  providers/          Anthropic, OpenAI and seven OpenAI-compatible vendors; registry.py
                      routes per role. OpenRouter has two rules of its own
                      (openrouter.py): its catalogue is filtered to the models that can
                      answer in JSON, and its key is proved against /key, because
                      /models answers 200 to anybody. EVREN has three (evren.py): a
                      catalogue filtered by task and capability, reasoning_effort sent
                      per model, and terms a person accepts on the Models page --
                      never Slipwright by itself
  gates/              build_cmd and test_cmd: env.py (what they may see),
                      runner.py (where they run), toolchains.py (what is installed
                      there, and which mobile platforms it can build)
  standards/          the RAG corpus: chunking, retrieval, fts.py (the one dialect split)
  store/              persistence. schema.py declares every table; db.py owns the engine
  api/                FastAPI. __init__.py is projects and jobs, settings.py is settings,
                      auth.py is accounts
  alembic/            migrations, in order

  accounts.py         signing up, proving an address, resetting a password
  attachments.py      files a person gives the agents: what is accepted, the text and
                      pictures taken out of it, and what each agent is told of it
  mail.py             SMTP, and the outbox that stands in for it
  demo.py             the worked example a new account starts with
  quota.py            what one account may take of a shared machine
  teams.py            the people an account puts on its agents
  translate.py        agent prose in the language it was not written in
  brief/discovery     what a project *is*, before any development starts
  worklist.py         what a development will do, grouped by agent
  update.py           a newer release, offered in the corner and installed on a press
  steps.py            what one pipeline step actually produced
  building.py         the build room: a development's phases as they are written and
                      built, and the machines writing them (web: components/BuildRoom)
  costs.py + prices.py  what a development cost against what it was expected to
  support.py          the support desk
  net.py              retrying a request that never left
  workers.py          a machine lent to an account: the connection code, the address in it
  worker_agent.py     `slipwright worker`, the machine's side; api/workers.py is the door
  providers/machine.py  a lent machine as a model provider: a phase written on its own
                      plan, falling back to the account's model when nobody answers
  relay/              machines on other networks: the server's room (host.py), a machine's
                      way in (guest.py), the seal (crypto.py). The Cloudflare relay itself
                      is the top-level relay/; the desktop app and slipwright-agent live in
                      their own repository, ksksertac/slipwright-agent; all
                      docs/machines-protocol.md
  transfer/           an account moved to another installation on the network: a code
                      that is a SPAKE2 password (channel.py), the sender (outgoing.py),
                      the receiver's staging and all-or-nothing write (incoming.py), and
                      looking around the LAN (nearby.py); api/transfer.py is the door
  notify/             Telegram, Slack, Discord and Teams: core.py decides who is asked
                      and what a press may do; listeners.py runs the bots

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
uv run slipwright db copy              # an installation's SQLite file -> SLIPWRIGHT_DATABASE_URL
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

### Getting a change onto main

`main` is protected by a ruleset: no direct pushes, only a pull request whose `test` check
(`.github/workflows/docker.yml`) has passed. Push a branch and open a PR. Every merge to
`main` is a **release**: CI publishes the image as the next patch (`v0.2.0` → `0.2.1`) and
`:latest`, tags the commit and writes a GitHub release from the merged PRs' titles, and
every running installation is offered it. A bigger step (`v0.3.0`) is a tag pushed by
hand; the patches count on from it.

**A release has to say what it brings, or nobody installs it.** The release page is what
a person sees before pressing *Update now*, and a page that reads only "A development is
sent without its history details" in a developer's shorthand gives them no reason to.
`--generate-notes` copies the merged PRs' *titles* and nothing else, so:

- The PR title is the release's headline. Write it as what a person running Slipwright
  will notice, in plain words -- not the name of the function that changed.
- The PR body opens with a short **What changes for you** section: what is new or fixed,
  where in the interface it is, and anything they must do (a setting, a restart, a
  migration that takes a while). Internals, tests and reasoning come after it.
- Once CI has published the release, put that section into the release's notes (edit
  the release through the API) so the page carries more than the one-line title. A
  release whose page says nothing is not finished.

**For now the test suite does not run in CI** (since 2026-10-01; it cost ~10 minutes a
PR). The `test` check runs ruff and mypy only, and the macOS job is off. So run
`uv run pytest -q` locally, against the branch as it will merge (rebased on `main`),
before every PR -- nothing else stands between a change and every installation. Both
are marked `TEMPORARILY OFF` in `docker.yml`, one line each to turn back on.

## Configuration

| Variable | Default | What it decides |
|---|---|---|
| `SLIPWRIGHT_DATABASE_URL` | SQLite under the state dir | PostgreSQL for a hosted install |
| `SLIPWRIGHT_STATE_DIR` | `.slipwright` | database, `secret.key` |
| `SLIPWRIGHT_WORK_DIR` | `<state>-work` | checkouts. **Never inside the state dir** |
| `SLIPWRIGHT_RUNNER` | `local` | `docker` for a container per command |
| `SLIPWRIGHT_QUOTA_MAX_*` | `0` (off) | running jobs, projects, disk |
| `SLIPWRIGHT_DEMO_PROJECT` | on | the worked example a new account starts with |
| `SLIPWRIGHT_CHATGPT_SUBSCRIPTION` | on locally, off when hosted | agents on a ChatGPT plan via the Codex CLI |
| `SLIPWRIGHT_MAX_CALLS_PER_PROVIDER` | `4` | model calls one account runs at once on one provider, across its developments; `0` = no limit |
| `SLIPWRIGHT_MODEL_TIMEOUT_S` | `1800` | how long one model call may take; a call given up on is billed in full |
| `SLIPWRIGHT_SECRET_KEY` | generated in the state dir | encrypts stored credentials. **Required** with PostgreSQL |
| `SLIPWRIGHT_UPDATE_IMAGE` | `ghcr.io/ksksertac/slipwright` | where releases are looked for; `off` stops asking |
| `SLIPWRIGHT_TRANSFER` | on locally, off when hosted | moving an account to another installation (Settings → Move) |
| `SLIPWRIGHT_RELAY` | `wss://relay.slipwright.app` | the relay machines on other networks come through; `off` never. Used only once *Machines → Reach machines on other networks* is on |

## How to write here

Match the surrounding code: it is unusually heavily commented, and the comments explain
*why*, not what. A comment that restates the line below it is noise; one that records the
reason a thing is the way it is, or the failure that shaped it, is the point.

Tests are named as sentences about behaviour (`test_a_job_is_run_on_its_owners_keys`) and
assert on what a person would notice, not on internals. When a test breaks because
behaviour deliberately changed, rewrite it to state the new rule -- do not weaken it.

## Traps

- **A read that polls asks for `details=False`.** A development's history details (diffs,
  logs) are most of its bytes; one 145 MB diff once made every poll of the page load,
  parse and send it -- two cores and 40 GB in six hours. `store.get`/`list` with
  `details=False` select `detail_size` instead (SQLite loads a value whole even for
  `length()`), and one entry is `store.transition(job_id, index)`. Every detail is bounded
  when written (`MAX_DETAIL`). The web reads an entry's detail when it is opened
  (`components/EntryDetail.ts`), never from the job.
- **`_may_act` guards the gates.** Approve, reject and the gate editors go through it. It
  also refuses the demo project. A new mutating endpoint that skips it has no guard.
- **The demo project has no checkout.** Anything that would run something in it must
  refuse (409) rather than fail deeper in. Deleting it is allowed -- that is its purpose.
- **A deleted development is kept, and read-only.** `remove_job` (the page's *Delete*)
  closes the pull request, deletes the branch, reverts what was merged with a commit
  pushed on top of the base branch (never forced), moves the Jira issues to Won't Do,
  and marks `data.removed` -- a field, not a state, so a release rolled back can still
  read the row. `_refuse_if_read_only` (the API) and `JobRemoved` (the engine) refuse
  every move after it; a new action on a job goes through one of them.
- **A chat press is a gate action.** `notify/core.py`'s `_refusal` is the chat twin of
  `_may_act`; a press counts only from the chat account linked to the person it was asked
  of, and only for the gate visit (`gate_marker`) it was asked about. Change one guard and
  change the other. `/api/notify/inbound/` is outside the login (`PUBLIC_PREFIXES`) and
  proves itself with Microsoft's signed token instead -- keep that check first.
- **`_resume_all` is deliberately unscoped.** The server starting is not somebody asking;
  in-flight work of every account must carry on, each on its own owner's credentials.
- **A worker's poll wakes developments, per account.** `AWAITING_BUILDER` is the one wait
  nobody approves: it opens when a machine that can build the phase is there. `/api/worker/`
  is outside the login like the Teams door; its token opens nothing else, and a worker is
  handed its own account's builds only (`claim_worker_task` filters on the owner). Never
  let the approve path or a gate editor reach that state -- there is nothing to approve.
- **A move carries an account, never a person.** `transfer/rows.py` lists what goes;
  users, sessions, tokens and memberships are not on it, and everything is rewritten on
  arrival to belong to whoever showed the code. `/api/transfer/peer/` is outside the login
  like the Mac's door: `pair` is the key exchange and every part after it must open with
  that key. Settings arrive decrypted inside the channel and are sealed again with the
  receiver's key -- so they are held in memory, never staged to disk. A new table that
  belongs to a project must be added to `TABLES`, or a move silently leaves it behind --
  and deleted in `_write` when a project is replaced. A project the receiver already has
  (its own account's) is replaced by the copy sent; `_cannot_replace` refuses when that
  would take a running development or delete one only the receiver has. The ChatGPT
  sign-in is Codex's `auth.json`, not a setting: it travels as its own part, in memory,
  and is written only where the receiver has none.
- **A machine writes, the server decides.** A phase a lent machine writes comes back as
  the model's text and goes through `invoke_role` like any vendor's answer; the server
  applies, builds, reviews and commits it. Never let a machine's answer skip that, and
  never wait on a machine that is not visibly at it -- unclaimed, quiet or failed, the call
  is taken back and the account's own model writes it (`providers/machine.py`).
- **The relay is a door for machines only.** It is off until somebody turns it on; the
  host serves nothing through it but `/api/worker/`, refuses a replayed or stale request,
  and the relay reads none of it. The room and its keys are the installation's
  (`relay.*` settings), never an account's, and never carried by a move.
- **A lost Mac is not a red build.** `BuilderLost` sends the job back to waiting with
  `builder_resume=build_gate`: the phase is written, only its build is owed, and no attempt
  is spent. Charging it as a failure would fail developments because a laptop went to sleep.
- **Nothing may depend on a platform phase.** Phases nothing here can build are moved
  behind the rest (`_put_unbuildable_last`); the Architect is told so. A plan where a
  backend phase needs what an iOS phase wrote would wait forever on a Windows server.
- **Alembic is quiet on purpose.** It narrates at INFO, which once landed in a CLI's
  stdout and corrupted a token it printed. `store/migrate.py` sets it to WARNING.
- **A new database is created and stamped in one transaction.** Both engines run DDL
  transactionally; without that, a half-built database came back with tables but no
  revision and could never be migrated.
- **`Permission.RUN_COMMANDS` and `NETWORK` were declared for a long time and never
  checked.** The first is enforced now. If you add a permission, enforce it in the same
  commit or do not add it.
- **A release is installed from the page** (`update.py`). The server cannot replace its
  own container, so a helper started from the *new* image does it over the Docker socket,
  carrying every volume over by name -- an anonymous `/data` included, which a naive
  re-create would hand an empty one. A release's migrations run against the database the
  previous release left; one that fails its health check is swapped back, but the
  schema is not, so a migration must leave the database usable by the release before.
  Since every merge is a release, that is every merge. The number an image reports is
  `SLIPWRIGHT_VERSION`, written into it by CI -- `pyproject.toml`'s is only a source
  checkout's, because CI cannot commit a bump to a protected `main`.
- **Stop is a pause; End is for good.** `pause` keeps the development's place in
  `data.pause` and waits in `paused`, which is neither working nor terminal, so
  `_resume_all` leaves it alone. `carry_on` without a pull refuses when somebody pushed to
  the branch meanwhile (`RemoteMoved`): building beside unseen commits ends in a refused
  push after every phase is paid for. A pull with phases left goes through `reconcile`
  and its gate, and only an unbroken run of phases finished by hand is passed over.
  `_stopping` carries both orders to a running loop; a cancel outranks a pause.
- **What a person says to an agent lives in `job_messages`, never in `data_json`.** The
  run saves the job whole from the copy it read when its step began, and a steering
  message kept in `data.inbox` was saved over by it. The store now reads the inbox from the
  table and a `save` only *adds* to it. An answer to a question (`roles/talk.py`) is a side
  call: it holds no lock, writes only its own row, and its cost waits there until whoever
  holds the job next folds it in (`_bill_answers`). Anything that writes to a job while it
  may be running wants the same shape.
- **A re-plan asked while a phase runs is a halt that carries on** (`_Halt("redirect")`):
  the run stops before its next call and goes to the Architect with the built phases kept
  (`_replan_from`), instead of ending. A stop or a pause that overtakes it marks it
  `dropped`, so the person is never left with a request that says "pending" forever.
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
| work done by hand | the Architect's reading of what people pushed while it was paused | owner, or the Architect's member |

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
