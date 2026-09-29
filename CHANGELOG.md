# Changelog

## 0.1.0

The first release. A team of agents builds what you ask for, and a person approves at
every gate.

### The pipeline

- A Product Owner turns a request into epics, stories and tasks; an Architect turns those
  into a profile, decisions and phases; a Designer draws the screens the UI specialists
  build; backend, web and mobile specialists build one phase at a time; QA proposes test
  cases and then writes them; DevOps proposes how it is deployed, writes the files, pushes
  the branch and opens the pull request.
- Seven gates a person answers: backlog, architecture, design, standards review, test
  cases, written tests, deployment. A stopped development can be retried, replanned with a
  note, or re-run a step at a time.
- Every development runs in its own git worktree, off its own branch. Nothing is committed
  to a default branch by an agent.
- The agents never talk to each other. A deterministic state machine calls one at a time,
  each answering with a typed JSON schema, and every transition is persisted before the
  next one runs.

### Whose keys, whose work

- Sign up with an email address, prove it, reset a password — all rate-limited, delivered
  over SMTP or held in an outbox when no mail server is configured.
- Everything has an owner. A row belonging to somebody else is *not found* rather than
  forbidden, the event stream filters at the source, and a job runs on its owner's
  credentials: model provider, Git token and Jira alike.
- Agent standards come in three layers — shipped, yours, this project's — and the most
  specific one wins, so one account's rule change is not everybody's.
- Invite people onto individual agents: they answer at their agent's gates and nowhere
  else.

### Models

- Anthropic, OpenAI and six OpenAI-compatible vendors (DeepSeek, Google, Alibaba, Z.ai,
  MiniMax, OpenRouter). Each agent can be pinned to its own provider and model.
- OpenRouter is one key for every vendor at once. Its catalogue is filtered to the models
  that can answer in JSON, since that is what every agent is asked for and OpenRouter
  drops the parameter rather than refusing; its key is proved against the endpoint that
  checks keys, because its model list answers anyone; and its prices come from its own
  catalogue, because a call bought through a reseller costs the reseller's rate.
- What a development cost, against what it was expected to cost, broken down by agent,
  phase and model. The call log is re-priced on the way out, so a call made before its
  model had a price is counted once the table catches up.

### Running it

- SQLite by default; PostgreSQL for a hosted installation, with Alembic migrations and one
  declared schema behind both.
- `SLIPWRIGHT_RUNNER=docker` runs a project's own build and test commands in a throwaway
  container with no network and no root. Their environment is an allow list: name a
  variable or it is not there.
- Quotas on running developments, projects and disk. All of it is opt-in — upgrading a
  local install must not find its work suddenly refused.

### From a chat

- Telegram, Slack, Discord and Teams are told when an agent is waiting, when a development
  stops and when one finishes. Somebody who links their own account is asked at their own
  gates, with two buttons.
- From Telegram you can also ask where things stand, what is waiting, what it cost and why
  something stopped — and start a development, which asks you to confirm before it spends
  anything.

### The interface

- English and Turkish. Interface text is translated from a table; what an agent *wrote* is
  translated through the server, so the same development reads in either language.
