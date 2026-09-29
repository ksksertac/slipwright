<div align="center">

<img src="web/public/logo.png" alt="Slipwright" width="96" />

# Slipwright

**A software team made of AI agents — and you approve every step.**

Write what you want built. A Product Owner turns it into a backlog, an Architect into a plan,
specialists build it phase by phase, QA writes the tests and DevOps opens the pull request.
Nothing moves past a gate until a person says yes.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/web-React-61DAFB?logo=react&logoColor=black)
[![Docker image](https://img.shields.io/badge/docker-ghcr.io%2Fksksertac%2Fslipwright-2496ED?logo=docker&logoColor=white)](https://github.com/ksksertac/slipwright/pkgs/container/slipwright)

[Features](#features) · [How it works](#how-a-development-flows) · [Getting started](#getting-started) · [Configuration](#configuration)

<br />

<img src="docs/screenshots/gate-test-cases.png" alt="A development waiting at the test-cases gate, with the supervisor's recommendation and QA's proposed cases open for editing" />

</div>

---

## Why Slipwright

Most coding agents are one model in a loop, and you find out what it did when it is
finished. Slipwright is built the other way round:

- **A team, not a chatbot.** Each role is its own agent with its own model, its own
  instructions and its own permissions. The agents never talk to each other; a
  deterministic state machine calls one role at a time and every answer is a typed schema.
- **You stay in charge.** The backlog, the architecture, the screens, the test cases, the
  tests and the deployment each stop at a gate. You edit what the agent proposed, approve
  it, or send it back with a reason.
- **Nothing is lost.** Every step is written to the database before the next one runs.
  Stop the server mid-development and start it again: running work carries on, work
  waiting for you keeps waiting.
- **Your keys, your repository.** It runs on your own model keys, pushes to your own
  GitHub or Bitbucket, and mirrors the backlog into your own Jira.

## How a development flows

```mermaid
flowchart LR
    R([Your request]) --> PO[Product Owner<br/>backlog]
    PO --> G1{{You approve}}
    G1 --> AR[Architect<br/>plan and phases]
    AR --> G2{{You approve}}
    G2 --> DEV[Specialists<br/>one phase at a time]
    DEV --> BG[Build gate<br/>and standards review]
    BG -->|next phase| DEV
    BG --> QA[QA<br/>test cases]
    QA --> G3{{You approve}}
    G3 --> QW[QA<br/>writes the tests]
    QW --> G4{{You approve}}
    G4 --> DO[DevOps<br/>deployment and PR]
    DO --> G5{{You approve}}
    G5 --> PR([Pull request])
```

A web or mobile phase is preceded by the **Designer**, whose screens have a gate of their
own. A failed build goes back to the same specialist (up to three times); red CI on the
pull request goes back to the developer who wrote the code.

---

## Features

### An agent for every role

<img src="docs/screenshots/agents.png" alt="The Agents page: one card per agent with its model, thinking depth, standards and permissions" />

| Agent | What it does |
|---|---|
| **Product Owner** | Reads the request and the repository, writes epics, stories and tasks |
| **Architect** | Chooses the stack, the build/test/run commands, the decisions and one phase per task |
| **Designer** | Draws the screens the web and mobile specialists will build |
| **Backend / Web / Mobile Developer** | Implement one phase each, in the phase's own domain |
| **QA** | Proposes test cases, then writes unit and end-to-end tests for the approved ones |
| **DevOps** | Proposes the deployment, writes it, pushes the branch and opens the pull request |
| **Supervisor** | Reads every gate and recommends approve or reject, with confidence and risk |

Every card shows which provider and model the agent runs on right now, how deeply it
thinks, which standards it reads and what it is allowed to do. Permissions
(`write_files`, `run_commands`, `git_push`, `jira`, …) are enforced by the engine, not
by the prompt.

### Gates you can edit, not just approve

<table>
<tr>
<td width="50%"><img src="docs/screenshots/gate-backlog.png" alt="The backlog gate: epics, stories and tasks editable in place" /></td>
<td width="50%"><img src="docs/screenshots/gate-architecture.png" alt="The architecture gate: decisions and phases editable in place" /></td>
</tr>
<tr>
<td><b>Backlog.</b> Rename epics, stories and tasks, add or remove tasks. The Architect designs one phase per task from what you approve.</td>
<td><b>Architecture.</b> Read the decisions, reorder phases, change a phase's domain or its files, and adjust the build, test and run commands.</td>
</tr>
</table>

Each gate offers **Save**, **Approve** and **Reject** with a reason, and the reason goes
back to the agent as feedback. Two gates also let you skip the step that follows,
because it is expensive and not always wanted:

- **Go on without tests.** You read the proposed cases and decide this change is not
  worth testing. QA writes nothing, and the cases stay on the record.
- **Go on without deployment.** You deploy by hand, or not at all. DevOps writes no
  deployment files and still opens the pull request with the code.

### One pipeline for every development

<img src="docs/screenshots/pipeline.png" alt="The project pipeline: one line per development, a finished one opened to its request, plan and four stages" />

A project's developments are one line each: what was asked, where it got to, and how far
along it is. Open one to see the four stages (planning, building, testing, delivery) as
step cards linked by arrows. Click any card to see what that step produced: a diff, a
build log, a backlog or a review. Gates waiting for you carry checkboxes, and
**Select all recommended** approves every gate the supervisor is confident about in one go.

### A supervisor at every gate

Per project, choose how much the supervisor does:

- **Manual.** You decide every gate yourself.
- **Assisted** (the default). Each gate carries a recommendation, with its confidence,
  its risk and its reasons.
- **Auto.** A confident, low-risk approval is made for you and recorded as such.
  Rejections are never automatic, the written-tests gate needs explicit permission, and
  any automatic approval can be undone from the dashboard.

When a build fails, the supervisor also decides whether the same specialist fixes it,
whether to re-plan, or whether to ask a person.

### Built behind a build gate, reviewed against your standards

After every phase, the project's own `build_cmd` and `test_cmd` run. A red build goes back
to the specialist; every green phase is committed on the development's branch. Then QA
reviews the diff against the **standards**: Markdown pages per domain (product,
architecture, backend, web, mobile, testing, devops), indexed for keyword and optional
embedding search. The sections relevant to a phase go into that agent's prompt. Review
can be `off`, `advisory` or `blocking`.

The standards are edited in the app, either for all projects or per project, and every
edit is linted, reindexed and committed.

### Any model, per agent

<img src="docs/screenshots/models.png" alt="Settings, Models: a card per provider with its key, base URL, default model and output limit" />

Anthropic (Claude), OpenAI (GPT), DeepSeek, Google (Gemini), Alibaba (Qwen), Z.ai (GLM)
and MiniMax work out of the box. On an installation you run for yourself, agents can also
run on a **ChatGPT subscription** through OpenAI's own Codex CLI, with no API credit.
Pin each agent to its own provider and model: a strong model for the Architect and a
cheap one for DevOps. Keys are stored encrypted, and **Test connection** tells you which
models each key can use.

### Your repository, your Jira

- **GitHub and Bitbucket.** Clone a private repository or use a local checkout. A
  finished development pushes its branch and opens a pull request, described from the
  plan, the test cases and the history. CI is watched, and a red run goes back to the
  developer.
- **Jira** (optional). The approved backlog is mirrored as epics, stories and sub-tasks.
  Issues move as tasks finish, and pull request links and failures are commented. The
  agents act as a bot account of your choosing, and only the roles you allow may touch
  Jira.

### A dashboard of what is happening, and what waits for you

<img src="docs/screenshots/dashboard.png" alt="The dashboard: counts, the last 14 days, where the developments stand, who did the work, pending approvals and recent activity" />

Running agents, approvals pending across every project (answerable right there),
developments by state, which agent did how much, and a live activity feed. A **Costs**
tab per project shows what each development spent against what it was expected to.
Per-project budgets on tokens, wall-clock time and model calls stop a runaway development
with a readable reason.

### Agents reach you where you already talk

<img src="docs/screenshots/notifications.png" alt="Notifications: Telegram, Slack, Discord and Microsoft Teams, with what a group is told" />

- **Group notifications** in Telegram, Slack, Discord or Microsoft Teams: the group is told
  when an agent is waiting, when a development stops and when one finishes. It is told,
  never asked.
- **Remote control** from Telegram: link your own chat account with a one-time code, and
  the gates that are yours come to you with **Continue** and **Reject** buttons. A
  rejection asks you why. You can also ask where a development is, or start a new one.

Telegram, Slack and Discord connect outward, so they work from a laptop with no public
address.

### A team around the agents

Put a colleague on an agent. They are invited by email, see your projects, and approve and
edit only at *that agent's* gates: the backlog belongs to the Product Owner's holder, the
plan to the Architect's, the test list to QA's. They see no settings and cannot start
developments. Work arriving at their gate is mailed to them.

### In your language

The interface is in English and Turkish. An agent writes in the project's own language,
which is also what Jira and the pull request see. Everything it wrote is shown in the
platform's language through a cached translation bridge, while the fields you edit keep
the project's language.

### Local or hosted, one codebase

| | **Local** | **Hosted** |
|---|---|---|
| Who writes the build commands | you | strangers |
| Database | SQLite file | PostgreSQL |
| Commands run | on the machine | in a throwaway container |
| Model keys | the installation's | each account's own |
| Quotas | off | on |

Signing up, email verification, password reset, per-account keys and quotas, and a
container per command are all there for a shared server. None of it is on by default, so
a local install stays a single command.

---

## Getting started

### 1. Run it

<details open>
<summary><b>From the published image</b> (nothing to clone or build)</summary>

Every push to `main` publishes `ghcr.io/ksksertac/slipwright:latest` (amd64 and arm64); a
`v1.2.3` tag publishes `:1.2.3` as well.

```sh
docker run -d --name slipwright -p 8500:8500 \
    -v slipwright-state:/data -v slipwright-work:/work \
    ghcr.io/ksksertac/slipwright:latest                 # http://localhost:8500
docker exec -it slipwright slipwright user add ada      # first login (becomes admin)
```

Keep `/data` and `/work` as **two separate volumes**. `/data` holds the key that decrypts
every stored credential, and a development's own commands must not be able to reach it
from a checkout.

</details>

<details>
<summary><b>With Docker Compose</b> (recommended for a local install)</summary>

One image holds everything: the API, the web UI, `git`, `gh`, `uv`/Python and Node for
the projects it works on. There is no separate database or queue to run.

```sh
cp .env.example .env                    # optional: API keys, a stable SLIPWRIGHT_SECRET_KEY
docker compose up --build -d            # http://localhost:8500
docker compose exec slipwright slipwright user add ada   # first login (becomes admin)
```

- **Local checkouts.** The folder named by `SLIPWRIGHT_REPOS` in `.env` (default
  `./repos/`) is mounted at `/repos`, so a checkout at `<that folder>/myapp` is registered
  as `/repos/myapp`. GitHub repositories are cloned into the volume.
- **Live environments.** Developments get ports `8100–8130`. Change `SLIPWRIGHT_PORT_RANGE`
  and the mapping in `compose.yaml` together.
- **Projects that call Docker** in their build need the socket mount that is commented out
  in `compose.yaml`.
- **Try it offline.** `SLIPWRIGHT_PROVIDER=scripted docker compose up` runs the whole
  pipeline on canned model replies, with no keys needed.

</details>

<details>
<summary><b>From source</b></summary>

```sh
uv sync                                  # Python side
cd web && npm install && npm run build   # web UI -> slipwright/api/static/
cd ..
uv run slipwright user add ada           # first login (prompted for a password; becomes admin)
uv run slipwright serve                  # http://127.0.0.1:8500
```

</details>

### 2. Connect your accounts

Open the app and log in. A **Getting set up** card on the dashboard walks you through it:

1. **Settings → Models.** Paste a key for at least one provider and click **Test
   connection**. A key in the server's environment (`ANTHROPIC_API_KEY`,
   `OPENAI_API_KEY`, …) is used when none is stored.
2. **Settings → Sources.** Add a GitHub or Bitbucket token. It clones private
   repositories, pushes branches and opens pull requests.
3. **Settings → Jira** *(optional).* Enter the site URL, email and API token. The approved
   backlog is then mirrored there.

### 3. Build something

1. **Projects → New project.** Pick a repository (or a local path) and, optionally, a Jira
   project. Slipwright reads the repository and proposes a brief of what the project is.
   Check it under **About the project**.
2. **New development.** Describe what you want, in plain words.
3. **Answer the gates** as they arrive: in the pipeline, on the dashboard, by email, or in
   Telegram. Edit what needs changing, approve, or reject with a reason.
4. **Follow along.** Every card in the pipeline opens what that step produced. Send a
   running development a message to steer it. The project's **Tests** tab runs its test
   command on the main checkout or on a development's branch, and lists every build gate
   that ran.
5. **Merge.** When it is done, the pull request link is on the development and in the
   activity feed.

A new account also starts with **Example: a Notes app**, a finished development to read
before you run one of your own. Delete it whenever you like.

---

## Using it from the command line

Client commands talk to the API with a bearer token. `slipwright token new <user>` prints
one; pass it as `--token` or `SLIPWRIGHT_TOKEN`.

```sh
uv run slipwright project new demo --github octocat/demo --jira DEM
uv run slipwright project list
uv run slipwright new <project-id> "add a /health endpoint"
uv run slipwright status                # or: slipwright status <job-id>
uv run slipwright approve <job-id>      # leave the current gate
uv run slipwright reject <job-id> "use poetry, not pip"
uv run slipwright message <job-id> "keep the public API unchanged"
```

The JSON API is documented at `/docs`, and `GET /api/events` streams server-sent events
for every change. `slipwright serve --no-auth` skips the login for trusted local use.

## Configuration

Settings come from the environment (or `serve` flags):

| Variable | Default | What it decides |
|---|---|---|
| `SLIPWRIGHT_STATE_DIR` | `.slipwright` | database, `secret.key` |
| `SLIPWRIGHT_WORK_DIR` | `<state>-work` | checkouts, clones, logs. **Never inside the state dir** |
| `SLIPWRIGHT_DATABASE_URL` | SQLite under the state dir | PostgreSQL for a hosted install |
| `SLIPWRIGHT_SECRET_KEY` | generated in the state dir | encrypts stored credentials. **Required** with PostgreSQL |
| `SLIPWRIGHT_PROVIDER` | `live` | `live` (real providers) or `scripted` (offline, canned replies) |
| `SLIPWRIGHT_PROFILE` | `examples/python-fastapi.profile.json` | the seed profile new projects start from |
| `SLIPWRIGHT_PORT` | `8500` | API and web UI port |
| `SLIPWRIGHT_PORT_RANGE` | `8100-8999` | ports handed to developments' live environments |
| `SLIPWRIGHT_AUTH` | `1` | `0` serves without login |
| `SLIPWRIGHT_RUNNER` | `local` | `docker` runs every build and test command in a throwaway container |
| `SLIPWRIGHT_QUOTA_MAX_*` | `0` (off) | per-account limits on running developments, projects and disk |
| `SLIPWRIGHT_DEMO_PROJECT` | on | the worked example a new account starts with |
| `SLIPWRIGHT_CHATGPT_SUBSCRIPTION` | on locally, off when hosted | offer **ChatGPT subscription (Codex)** under Settings → Models |
| `SLIPWRIGHT_DEV` | `0` | allow the Vite dev server's origin (CORS) |

### Moving to PostgreSQL

SQLite is the default and needs nothing. To keep everything in PostgreSQL instead, add
this to `.env`:

```sh
SLIPWRIGHT_DATABASE_URL=postgresql+psycopg://slipwright:slipwright@postgres/slipwright
COMPOSE_PROFILES=postgres       # so a plain `docker compose up` starts the database too
```

Then, if the installation already has people and projects in its SQLite file:

```sh
docker compose up --build -d
docker compose exec slipwright slipwright db copy   # SQLite file -> PostgreSQL
docker compose restart slipwright                   # pick up in-flight work from the copy
```

`db copy` refuses a database that already has accounts, so running it twice does no harm.
It leaves the SQLite file where it was, so removing `SLIPWRIGHT_DATABASE_URL` goes back to
it. Stored credentials travel still encrypted: keep the same `SLIPWRIGHT_SECRET_KEY`, or
the same `/data` volume, where `secret.key` lives.

### A ChatGPT plan instead of API credit

On an installation you run for yourself, **Settings → Models** offers *ChatGPT
subscription (Codex)*. First turn on *Enable device code sign-in for Codex* under ChatGPT →
Settings → Security. Then **Sign in with ChatGPT** shows a link and a one-time code, and
any agent can be pinned to it. Slipwright does not talk to ChatGPT itself: it runs
OpenAI's own Codex CLI (`codex exec`), signed in with your account. The option is off on
a hosted installation, where it would spend other people's plans on a shared machine. A
Claude subscription is deliberately not offered, because Anthropic does not allow
third-party products to sign in with claude.ai. Use an API key instead.

<details>
<summary><b>Tuning the model and thinking depth per agent</b></summary>

Every project starts from a **seed profile**. The Architect may rewrite the project facts
in it, but the `roles` map always comes from the seed: which model plays which role is a
person's decision, never a model's.

```json
"roles": {
  "po":        { "model": "claude-sonnet-5",  "thinking_depth": "medium", "permissions": ["read_files", "jira"] },
  "architect": { "model": "claude-opus-5",    "thinking_depth": "high",   "permissions": ["read_files", "run_commands", "jira"] },
  "backend":   { "model": "claude-opus-5",    "thinking_depth": "high",   "permissions": ["read_files", "write_files", "run_commands"] },
  "web_ui":    { "model": "claude-opus-5",    "thinking_depth": "high",   "permissions": ["read_files", "write_files", "run_commands"] },
  "mobile_ui": { "model": "claude-opus-5",    "thinking_depth": "high",   "permissions": ["read_files", "write_files", "run_commands"] },
  "qa":        { "model": "claude-sonnet-5",  "thinking_depth": "medium", "permissions": ["read_files", "write_files", "run_commands"] },
  "devops":    { "model": "claude-haiku-4-5", "thinking_depth": "low",    "permissions": ["read_files", "write_files", "run_commands", "network", "git_push"] }
}
```

- **`provider`** picks the vendor for a role. Unset, the role follows the default provider
  *and* that provider's default model (Settings → Models).
- **`model`** is passed to the provider verbatim. Change it in the profile and that role
  runs on the new model, with no code change and no restart.
- **Agents → (agent) → Setup** pins an agent to a provider and model for *every* project,
  over whatever the profiles say. Saving is refused when the provider has no key.
- **`thinking_depth`** is `off`, `low`, `medium`, `high` or `max`. Use `low` for
  mechanical roles (DevOps) and `high` where correctness matters (Architect, developers).
  Models with fixed thinking budgets (such as Haiku 4.5) want `off`.
- **`permissions`** are enforced by the engine: a developer without `write_files` cannot
  change the checkout, and DevOps without `git_push` cannot open a pull request.

</details>

## Development

```sh
uv run pytest                            # the whole suite, on SQLite
uv run ruff check . && uv run mypy       # lint and types
uv run python scripts/export_schema.py   # after changing API models or routes
cd web && npm run gen:api && npm run lint && npm run build
```

`schemas/openapi.json` and the generated TypeScript client are committed, and a test fails
when either is stale. `npm run dev` in `web/` serves the UI with hot reload against a
`slipwright serve` started with `SLIPWRIGHT_DEV=1`. To run the whole suite against
PostgreSQL, set `SLIPWRIGHT_TEST_DATABASE_URL`.

[CLAUDE.md](CLAUDE.md) is the orientation for anyone (or any agent) working on the code:
the layout, the rules that are easy to break, and the mistakes already made.
[TASKS.md](TASKS.md) is the build plan, with the design notes behind each phase.

## License

[Apache 2.0](LICENSE)
