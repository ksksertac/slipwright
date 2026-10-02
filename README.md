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

<img src="docs/demo.gif" alt="From the Agents page to a new project linked to Jira. The backlog and plan are approved and become issues on the Jira board; the Designer's screens are opened at full size, web and mobile, and approved; QA's test cases are approved from Telegram; the tasks move to Done on the board; DevOps proposes an AWS deployment on ECS Fargate, writes the Dockerfile, task definition, deploy script and workflow, pushes the branch and opens the pull request; and the bot answers /status" />

<sub>Recorded against the scripted provider — no model, no key. Telegram, Jira and GitHub are local stand-ins that Slipwright's own code talks to: the press on the phone is what approves the gate, and the branch is really pushed. <code>uv run python scripts/demo.py</code> sets the same thing up.</sub>

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

When you want to write a piece yourself, **Stop** a development, wherever it is. It keeps
its place -- the step, the phase, everything written so far -- and **Stop and push** sends
the branch to the repository as it stands, so people can check it out and work on it.
**Carry on** picks up exactly where it stopped; **Pull and carry on** merges what people
pushed first, the Architect reads what they did against the plan, and once you approve
that reading the phases they finished are not built again.

And when a development has gone somewhere nobody wants, **End** it. Ending is not
failing: nothing went wrong, so there is no red and no retry, and the branch with
everything built so far stays where it is. Either way a call already in flight is allowed
to finish, because its answer is already paid for; nothing after it begins.

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
and MiniMax work out of the box, as does **OpenRouter** — one key for every vendor at
once, priced at what OpenRouter charges rather than what the vendor does. Its catalogue
is filtered to the models that can actually answer in JSON, which is what every agent is
asked for. **EVREN** runs open-weight models on hardware in Turkey, with an *LLM
Çıkarım* key from evren.ssyz.org.tr; it wants its terms of use accepted before the first
call, and the Models page shows them and accepts them when you press the button. On an
installation you run for yourself, agents can also run on a **ChatGPT subscription**
through OpenAI's own Codex CLI, with no API credit.
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

### Remote control: run it from Telegram

Link your Telegram account once, and you can answer gates, check on your projects and
start new work from your phone without opening the app. The bot reads your account and
nobody else's.

<table>
<tr>
<td width="33%" valign="top"><img src="docs/screenshots/remote-gates.png" alt="Telegram: the bot is linked, a test-cases gate is approved, an architecture gate is rejected with a reason" /></td>
<td width="33%" valign="top"><img src="docs/screenshots/remote-asking.png" alt="Telegram: /projects, /waiting and /status answered from the account's own developments" /></td>
<td width="33%" valign="top"><img src="docs/screenshots/remote-starting.png" alt="Telegram: /new, one sentence, a confirmation with Yes and No buttons, and the development starts" /></td>
</tr>
<tr>
<td valign="top"><b>A gate comes to you.</b> When an agent waits on a gate that is yours, the bot sends what is waiting, the supervisor's advice and a link. Press <b>Continue</b> to approve. Press <b>Reject</b> and the bot asks why; your answer goes back to the agent as feedback.</td>
<td valign="top"><b>Ask where things stand.</b> <code>/projects</code>, <code>/waiting</code>, <code>/status</code>, <code>/running</code> and <code>/cost</code> are answered straight from your data, at no model cost. You can also just write a question in your own words.</td>
<td valign="top"><b>Start a development.</b> <code>/new</code>, one sentence saying what should be built, and a <b>Yes</b>. Nothing starts until you confirm, because a development spends your own model credit. <code>/project</code> sets up a new project the same way.</td>
</tr>
</table>

<img src="docs/screenshots/remote-page.png" alt="The Remote control page: the bot token, and linking your own Telegram account" />

**Setting it up takes two minutes.** Create a bot with [@BotFather](https://t.me/BotFather),
paste its token under **Remote control**, then press **Get a link code** and **Open in
Telegram**. That opens the bot with a one-time code (good for 30 minutes) that proves the
Telegram account is yours. Everybody on the account can link their own. From then on:

- **A gate only goes to its own people.** It goes to the account owner, or to the person
  who holds that agent, under the same rules as the web page. A button pressed by anybody
  else does nothing.
- **An answer counts once.** If a gate was answered elsewhere in the meantime (on the
  page, or by somebody else), a late press is told so and changes nothing.
- **Commands work in both languages**, English and Turkish (`/durum`, `/bekleyen`,
  `/yeni`, …). `/cancel` drops a conversation halfway through.
- **No public address needed.** The bot fetches its own updates, so it works from a
  laptop behind a router.

### Your team hears about it too

<img src="docs/screenshots/notifications.png" alt="Notifications: Telegram, Slack, Discord and Microsoft Teams, with what a group is told" />

A group in **Telegram**, **Slack**, **Discord** or **Microsoft Teams** is told when an
agent is waiting, when a development stops (with the reason) and when one finishes (with
the pull request). A group is told, never asked: anybody in the room could press a button,
and a gate is its owner's to decide. Telegram, Slack and Discord connect outward, so they
work without a public address.

### A team around the agents

Put a colleague on an agent. They are invited by email, see your projects, and approve and
edit only at *that agent's* gates: the backlog belongs to the Product Owner's holder, the
plan to the Architect's, the test list to QA's. They see no settings and cannot start
developments. Work arriving at their gate is mailed to them.

### Two-step sign-in

<table>
<tr>
<td width="50%" valign="top"><b>Turn it on in a minute.</b> Scan a QR code with any authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, …) and type the six digits back. Eight recovery codes are shown once, to copy or download, for the day the phone is lost.</td>
<td width="50%" valign="top"><b>Then every sign-in asks for a code</b> after the password. Each code and each recovery code works once. A link from a letter (verification, password reset, invitation) no longer signs you in around it: it does its job and sends you to sign in with the code.</td>
</tr>
</table>

It is **optional and per person**. The setup wizard offers it with a **Skip for now**, and
the **Security** page keeps offering it to everybody, team members included. Turning it
off asks for your password *and* a code. Somebody who has lost both phone and recovery
codes can have it taken off by an administrator (the Users page), and an installation
whose only administrator is locked out has `slipwright user two-factor-off <name>`. The
secret is stored encrypted with the installation key, like every other credential.

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

Signing up, email verification, password reset, two-step sign-in, per-account keys and
quotas, and a container per command are all there for a shared server. None of it is on by default, so
a local install stays a single command.

---

## Getting started

### 1. Run it

<details open>
<summary><b>From the published image</b> (nothing to clone or build)</summary>

Every merge to `main` is a release: it publishes `ghcr.io/ksksertac/slipwright:latest`
(amd64 and arm64) together with its own number, the next patch after the newest release
(`:0.2.1`, then `:0.2.2`, …), and a `:0.2` that follows the newest of them.

```sh
docker run -d --name slipwright --restart unless-stopped -p 8500:8500 \
    -v slipwright-state:/data -v slipwright-work:/work \
    -v /var/run/docker.sock:/var/run/docker.sock --group-add 0 \
    ghcr.io/ksksertac/slipwright:latest
```

Then open http://localhost:8500.

The Docker socket is what lets the page install a new release by itself (below). Access
to the socket is access to the host, which is fine on your own machine. On a server
other people sign up to, leave out the `-v /var/run/docker.sock...` line and update by
hand. `--group-add` is the socket's group on the host: `0` on Docker Desktop, `stat -c %g
/var/run/docker.sock` on Linux.

Open the page and sign in: a server with nobody on it yet makes an account for you,
`admin` / `admin`, and the login page says so. Change the password under **Settings →
Users**; until you do, a banner keeps reminding you.

Keep `/data` and `/work` as **two separate volumes**. `/data` holds the key that decrypts
every stored credential, and a development's own commands must not be able to reach it
from a checkout.

**Updating keeps your work.** Everything lives in the two volumes, not in the container.
When a newer release is out, an **Install version …** button appears under the version
in the sidebar's corner, for whoever is using the screen. It pulls the release, copies a
SQLite database aside, makes the container again on the same volumes, ports and
settings, and puts the old one back if the new one never becomes healthy. The database
is migrated at start, and developments that were running carry on.

A container started without the socket cannot do that, and the button shows what to run
instead -- the same steps by hand, which also give the new container the socket:

```sh
docker pull ghcr.io/ksksertac/slipwright:latest
docker stop slipwright && docker rm slipwright
docker run -d --name slipwright --restart unless-stopped -p 8500:8500 \
    -v slipwright-state:/data -v slipwright-work:/work \
    -v /var/run/docker.sock:/var/run/docker.sock --group-add 0 \
    ghcr.io/ksksertac/slipwright:latest
```

`docker rm` removes the container, not the volumes. Never `docker volume rm` or `docker
compose down -v` an installation you want to keep. Every merge to `main` is a release,
numbered one patch up from the last.

</details>

<details>
<summary><b>With Docker Compose</b> (recommended for a local install)</summary>

One image holds everything: the API, the web UI, `git`, `gh`, `uv`/Python and Node for
the projects it works on. There is no separate database or queue to run.

`.env` is optional: API keys, a stable `SLIPWRIGHT_SECRET_KEY`.

```sh
cp .env.example .env
docker compose up --build -d
```

Then open http://localhost:8500 and sign in as `admin` / `admin`.

To update: `git pull && docker compose up --build -d`. The volumes, and everything in them,
stay.

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

The Python side, then the web UI (built into `slipwright/api/static/`), then the server:

```sh
uv sync
cd web && npm install && npm run build
cd ..
uv run slipwright serve
```

Then open http://127.0.0.1:8500 and sign in as `admin` / `admin`.

</details>

### 2. Connect your accounts

The first time you sign in, a **setup wizard** takes you through it one step at a time,
starting at the first thing still to do. Each step's button opens the page where it is
done, and **Back to setup** on that page brings you back to the next one. Anything
optional has a **Skip for now**.

1. **A model key** (Settings → Models). Paste a key for at least one provider, click **Test
   connection** and pick its default model. A key in the server's environment
   (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …) is used when none is stored. One
   **OpenRouter** key reaches every vendor at once.
2. **GitHub or Bitbucket** (Settings → Sources). A token to clone private repositories,
   push branches and open pull requests.
3. **Jira** *(optional).* The site URL, email and API token; the approved backlog is then
   mirrored there.
4. **Two-step sign-in** *(optional).* Done right in the wizard: scan, type six digits, keep
   the recovery codes.
5. **Your first project.**

Close it and it waits as a checklist on the dashboard, with **Continue
setup**; the next sign-in offers it again until the required steps are done or you say
**Do not show this again**. Which steps are done is read from what is really configured,
so removing a key puts its step back.

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
uv run slipwright status
uv run slipwright status <job-id>
uv run slipwright approve <job-id>
uv run slipwright reject <job-id> "use poetry, not pip"
uv run slipwright message <job-id> "keep the public API unchanged"
```

On the server itself, `slipwright user add <name>` makes a login, `slipwright user
two-factor-off <name>` lets back in somebody who lost both phone and recovery codes, and
`slipwright db copy` moves an installation's SQLite file into PostgreSQL.

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
| `SLIPWRIGHT_DEFAULT_ADMIN` | `1` | `0` stops an empty server making `admin` / `admin`. Set it on anything reachable from the internet |
| `SLIPWRIGHT_RUNNER` | `local` | `docker` runs every build and test command in a throwaway container |
| `SLIPWRIGHT_QUOTA_MAX_*` | `0` (off) | per-account limits on running developments, projects and disk |
| `SLIPWRIGHT_DEMO_PROJECT` | on | the worked example a new account starts with |
| `SLIPWRIGHT_CHATGPT_SUBSCRIPTION` | on locally, off when hosted | offer **ChatGPT subscription (Codex)** under Settings → Models |
| `SLIPWRIGHT_UPDATE_IMAGE` | `ghcr.io/ksksertac/slipwright` | where newer releases are looked for; `off` stops asking |
| `SLIPWRIGHT_TRANSFER` | on locally, off when hosted | **Settings → Move**: move an account to another Slipwright on the network |
| `SLIPWRIGHT_NAME` | the host name | what this installation is called on another's **Move** page |
| `SLIPWRIGHT_DEV` | `0` | allow the Vite dev server's origin (CORS) |

### Moving to PostgreSQL

SQLite is the default and needs nothing. To keep everything in PostgreSQL instead, add
this to `.env`:

```ini
SLIPWRIGHT_DATABASE_URL=postgresql+psycopg://slipwright:slipwright@postgres/slipwright
COMPOSE_PROFILES=postgres       # so a plain `docker compose up` starts the database too
```

Then, if the installation already has people and projects in its SQLite file,

start it, copy the SQLite file into PostgreSQL, and restart so in-flight work is picked
up from the copy:

```sh
docker compose up --build -d
docker compose exec slipwright slipwright db copy
docker compose restart slipwright
```

`db copy` refuses a database that already has accounts, so running it twice does no harm.
It leaves the SQLite file where it was, so removing `SLIPWRIGHT_DATABASE_URL` goes back to
it. Stored credentials travel still encrypted: keep the same `SLIPWRIGHT_SECRET_KEY`, or
the same `/data` volume, where `secret.key` lives.

### Moving to another computer

A new laptop, or the work moving from one desk to another: **Settings → Move** on both.

1. On the computer the work goes **to**, press **Receive here**. A code shows for thirty
   seconds, then the next one (the last one still works while you type it).
2. On the computer it comes **from**, the installations on the same network are cards;
   press the one that is receiving and type its code. Not listed -- the server is in
   Docker and opened at `localhost`, say? *Connect by address* takes the address the
   receiving card shows.

Everything the account has goes, all at once or not at all: projects, developments at
whatever gate they stopped at, their history, attachments, briefs, standards pages, and
settings with the model keys and Git and Jira tokens -- sealed again with the receiving
installation's own key. Every checkout goes as the repository itself, with its branches,
pushed or not, and the work not yet committed. A ChatGPT sign-in goes with the settings,
so agents on a ChatGPT plan carry on without signing in again; one the receiver already
has is kept. An administrator's move also carries the installation's settings (mail,
prices) to an installation whose administrator received it.

Moved there once and worked on further here? Move it again: a project the receiver
already has is replaced with the copy sent -- its checkout, developments and history.
The move stops instead, and says which, when the receiver has a development of that
project running, or one started there that the sender does not have, since replacing the
project would delete it. A project that is another account's on the receiver is left
alone.

People do not move. Accounts, sessions, sign-in and team memberships stay where they are;
on arrival everything belongs to whoever showed the code. A connected Mac is paired again.

The code is the input to a key exchange (SPAKE2), not a password sent to be checked:
nothing on the network can be tested against a guess, and the first attempt spends it.
Both computers must run the same version, and nothing may be running -- a development
waiting at a gate is fine. *Delete them from this computer* removes the projects from the
sender once the receiver has written them.

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

### Your team's computers: Machines

The agents' phases are written by models, and the people on an account usually have
models of their own: a Claude Code or ChatGPT plan, or a key. **Settings → Machines**
lends a computer to the account so phases are written there, on that plan, side by side
with the rest -- the owner's computers and every team member's.

1. Install the **Slipwright Agent** app (`desktop/`, macOS, Windows and Linux) and open it.
2. **Machines → Connect a machine** makes a code; paste it into the app under
   *Slipwright team*. A member makes their own; the machine is theirs, and the owner sees
   it too.
3. In the app, choose which agents the computer runs -- Backend, Web, Mobile, DevOps --
   and on which model: Claude Code or Codex as installed and signed in, or an Anthropic
   or OpenAI key. A GitHub or Bitbucket token lets the model read the repository itself;
   a Jira token moves the issue to *In Progress* in your own name.

The server still decides everything: a machine's answer is checked like any model's, then
applied, built, reviewed, committed and pushed here. A computer that sleeps, loses its
network or runs out of plan costs nothing but the wait -- its phase is written by the
account's own model instead. What a machine writes is on its own plan, not the account's
bill.

**Not on the same network?** Turn on **Machines → Reach machines on other networks**. The
server then keeps a connection open to `relay.slipwright.app`, and codes carry its room
there instead of an address; a machine anywhere comes in through it, nothing is opened on
either side, and everything is sealed end to end -- the relay passes it on and can read
none of it. `SLIPWRIGHT_RELAY` points an installation at a relay of its own (`relay/`), or
`off` keeps it from ever using one.

### Mobile apps: the Mobile Builder

An iOS app is built by Xcode, Xcode runs only on macOS, and no container can hold macOS:
Docker on a Mac runs a Linux VM too. Android's build tools exist for Linux on x86_64 only,
so on an Apple Silicon Mac the image cannot build Android either. Slipwright stays where it
is, and the **Mobile Builder** -- a small helper on a Mac, outside Docker -- does the builds
it cannot do: iOS with Xcode, Android with Android Studio. The server may be on that same
Mac, in Docker, or on another machine.

A development with an iOS app builds everything else as usual, then stops at **Waiting for
the Mobile Builder**. Nothing has failed and nothing is spent; when it connects the
development carries on by itself.

1. **Settings → Machines → Connect a machine.** Nothing is asked. The code carries the
   server's address when it has one; a page open at `localhost` has none to give (Docker
   cannot see the address of the machine it runs on), so its code carries only the port,
   and the Mac looks for the server itself: on the Mac first, then on its own network.
2. **On the Mac**, install the worker once and run the command the page shows:
   ```bash
   brew install uv
   uv tool install --force git+https://github.com/ksksertac/slipwright
   slipwright worker --connect SW-7KQ4-M2XD-9FHA-T3WN-P6RB
   ```
   The code works once, for fifteen minutes. `slipwright worker status` says what the Mac
   can build: Xcode for iOS (install it from the App Store and open it once), Android
   Studio for Android.
3. **`slipwright worker service install`** starts it at login from then on
   (`~/Library/Logs/slipwright-worker.log`).

The worker is not in Docker -- it has to reach Xcode -- and it calls the server; nothing is
opened on the Mac. It builds only its own account's apps, each in a fresh directory that is
deleted afterwards, with nothing of the Mac's environment but what a build needs.

- **Run it as a macOS user of its own.** The commands it runs are written by a model; under
  your own user they could read your Keychain and SSH keys.
- **The same network** is simplest. The server's machine keeps its address if your router
  reserves it (DHCP reservation). For a Mac elsewhere, [Tailscale](https://tailscale.com)
  gives both a stable address.
- **The server on the same Mac, in Docker?** Run the worker beside it, outside Docker; it
  finds the server at `localhost` by itself.
- **The Mac on another network** cannot be found by looking around. Turn on **Reach
  machines on other networks** (above), or give the installation an address of its own
  (the base URL under **E-mail**) and every code carries it.

## Development

The whole suite on SQLite, lint and types, the API schema (after changing API models or
routes), then the web client and UI:

```sh
uv run pytest
uv run ruff check . && uv run mypy
uv run python scripts/export_schema.py
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
