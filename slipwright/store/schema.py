"""Every table Slipwright keeps, in one place.

The store used to be hand-written SQLite: one ``CREATE TABLE`` string per module and a
tuple of ``ALTER TABLE`` statements applied by hand. A hosted installation runs on
PostgreSQL, so the tables are declared once here with SQLAlchemy Core and the same
declarations serve both engines -- SQLite for a local install and for the test suite,
PostgreSQL for a server.

Two conventions are deliberate and worth knowing before changing anything:

* **Timestamps are ISO-8601 text, not a native timestamp type.** Every column was written
  that way by the SQLite store and every reader parses it with ``datetime.fromisoformat``.
  Keeping the type means an existing database opens unchanged and no reader moves.
* **Rich objects are JSON text.** A job's data, a project, a profile, a test run and a
  brief are Pydantic models serialised whole into ``*_json`` columns. Only the columns a
  query filters or orders by are broken out. That is why the shape of a plan can grow
  without a migration.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

# -- projects, jobs and their history ---------------------------------------------------

projects = Table(
    "projects",
    metadata,
    Column("id", String(64), primary_key=True),
    # who it belongs to. Null on projects made before accounts owned anything, which the
    # store treats as "the installation's", visible to whoever runs it.
    Column("owner_id", String(64)),
    Column("name", Text, nullable=False),
    Column("data_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("projects_owner", "owner_id", "created_at"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64)),
    # copied from the project at creation. Denormalised on purpose: listing jobs is the
    # hottest query there is and it must not need a join to know who may see them.
    Column("owner_id", String(64)),
    Column("request", Text, nullable=False),
    Column("repo_path", Text, nullable=False),
    Column("worktree_path", Text),
    Column("port", Integer),
    Column("state", Text, nullable=False),
    Column("profile_json", Text),
    Column("data_json", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("jobs_project_id", "project_id", "created_at"),
    Index("jobs_owner", "owner_id", "created_at"),
)

# Phase transitions are only ever appended; ``update_state`` writes the row and the job's
# new state in one transaction so the two can never disagree.
job_history = Table(
    "job_history",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("job_id", String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
    Column("from_state", Text, nullable=False),
    Column("to_state", Text, nullable=False),
    Column("at", Text, nullable=False),
    Column("note", Text),
    Column("detail", Text),
    Index("job_history_job_id", "job_id", "seq"),
)

test_runs = Table(
    "test_runs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("job_id", String(64)),
    Column("started_at", Text, nullable=False),
    Column("data_json", Text, nullable=False),
    Index("test_runs_project", "project_id", "started_at"),
)

# What Slipwright knows about a project before any development starts: the analysis of an
# existing checkout, or the intake conversation for an empty one.
project_briefs = Table(
    "project_briefs",
    metadata,
    Column("project_id", String(64), primary_key=True),
    Column("state", Text, nullable=False),
    Column("data_json", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# What the agents wrote, in the language they did not write it in. Keyed by the source
# text, so the same sentence is translated once and met again for free.
translations = Table(
    "translations",
    metadata,
    Column("lang", String(8), primary_key=True),
    Column("source", Text, primary_key=True),
    Column("text", Text, nullable=False),
    Column("at", Text, nullable=False),
)

# -- accounts ---------------------------------------------------------------------------

users = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("username", Text, nullable=False, unique=True),
    # the login identity. Nullable because accounts made before signup existed have none;
    # they keep logging in by username until an address is added.
    Column("email", String(320), unique=True),
    Column("email_verified_at", Text),
    # set on somebody an administrator invited onto an agent: the account they belong to.
    # Null on an account that is its own, which is every account that signed itself up.
    Column("owner_id", String(64)),
    # active | suspended | invited | removed
    Column("status", Text, nullable=False, server_default="active"),
    Column("password_hash", Text, nullable=False),
    Column("is_admin", Integer, nullable=False, server_default="0"),
    Column("created_at", Text, nullable=False),
)

# Who is on which agent. One row per (account, agent, person): an agent belongs to the
# account, so a membership is not per project either. The row outlives the membership --
# declined, left and removed all stay -- because the list of who approved what is read
# long after somebody has moved on, and because the invited address stays taken.
agent_members = Table(
    "agent_members",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("owner_id", String(64), nullable=False),  # whose agent
    Column("role", String(32), nullable=False),  # po | architect | backend | ...
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("email", String(320), nullable=False),
    Column("name", Text, nullable=False, server_default=""),
    # invited | active | declined | left | removed
    Column("status", Text, nullable=False, server_default="invited"),
    Column("invited_by", String(64)),
    Column("invited_at", Text, nullable=False),
    Column("responded_at", Text),
    Column("ended_at", Text),
    Index("agent_members_owner", "owner_id", "role"),
    Index("agent_members_user", "user_id"),
)

# One-shot links sent by mail: prove an address, or set a new password. Only the hash is
# kept, so the database cannot be read back into a working link.
email_tokens = Table(
    "email_tokens",
    metadata,
    Column("token_hash", String(128), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),  # verify | reset | invite
    Column("email", String(320), nullable=False),  # the address it was sent to
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("used_at", Text),
    Index("email_tokens_user", "user_id", "kind"),
)

# A counter per (action, who) in a sliding window: signups, logins and reset requests are
# cheap to ask for and expensive to serve, so they are rationed.
rate_limits = Table(
    "rate_limits",
    metadata,
    Column("bucket", String(255), primary_key=True),
    Column("window_start", Text, nullable=False),
    Column("count", Integer, nullable=False, server_default="0"),
)

# Mail that was not sent anywhere: the transport used by the test suite and by an
# installation with no SMTP configured yet, so a verification link is never simply lost.
email_outbox = Table(
    "email_outbox",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("to_address", String(320), nullable=False),
    Column("subject", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("at", Text, nullable=False),
)

# What somebody wrote on the support page. The letter goes to the support address the
# moment it is written; the row is what survives a mail server that was down, and what
# the admin page lists. ``delivery`` says which of the two happened.
support_requests = Table(
    "support_requests",
    metadata,
    Column("id", String(64), primary_key=True),
    # who asked. Kept as a plain column rather than a foreign key: a request outlives the
    # account that wrote it, and an answer is owed either way.
    Column("user_id", String(64)),
    Column("name", Text, nullable=False, server_default=""),
    Column("email", String(320), nullable=False),
    Column("category", Text, nullable=False, server_default="other"),
    Column("subject", Text, nullable=False),
    Column("message", Text, nullable=False),
    # sent | outbox | failed -- where the letter ended up, and why if nowhere
    Column("delivery", Text, nullable=False, server_default="outbox"),
    Column("delivery_error", Text),
    Column("sent_to", String(320)),
    # open | closed. Nothing closes one automatically; an admin marks it handled.
    Column("status", Text, nullable=False, server_default="open"),
    Column("created_at", Text, nullable=False),
    Column("closed_at", Text),
    Index("support_requests_user", "user_id", "created_at"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", String(128), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
)

api_tokens = Table(
    "api_tokens",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("token_hash", String(128), nullable=False, unique=True),
    Column("created_at", Text, nullable=False),
    Column("last_used_at", Text),
    Column("revoked_at", Text),
)

# -- configuration ----------------------------------------------------------------------

# Named settings; values marked secret are encrypted at rest with the installation key.
#
# ``user_id`` is what makes an installation multi-tenant: a row with one belongs to that
# account (its model keys, its Git tokens, its Jira, which model each of its agents uses),
# and a row without belongs to the installation (mail, prices, webhooks). The empty string
# stands in for "the installation" because a primary key column cannot be null.
settings = Table(
    "settings",
    metadata,
    Column("user_id", String(64), primary_key=True, server_default=""),
    Column("name", Text, primary_key=True),
    Column("value_json", Text, nullable=False),
    Column("encrypted", Integer, nullable=False, server_default="0"),
    Column("updated_at", Text, nullable=False),
)

# The price of a million tokens, in US dollars. Vendors publish no pricing API, so these
# are fetched daily from a public table or typed in by hand; ``source`` keeps the two
# apart so a refresh never clobbers a manual rate.
model_prices = Table(
    "model_prices",
    metadata,
    Column("provider", String(64), primary_key=True),
    Column("model", String(255), primary_key=True),
    Column("input_usd", Float, nullable=False),
    Column("output_usd", Float, nullable=False),
    Column("source", Text, nullable=False),  # litellm | manual
    Column("at", Text, nullable=False),
)


# -- the standards index ----------------------------------------------------------------

# Standards pages chopped into sections and indexed for retrieval. Derived data: it is
# rebuilt from the Markdown whenever the corpus fingerprint changes, so it carries no
# truth of its own and may be dropped at any time.
# A standards page as one account rewrote it.
#
# The pages that ship with Slipwright are files in the package and stay read-only. When
# somebody changes one, the changed copy is written here and *shadows* the shipped page
# for that account alone -- which is the whole point: on a hosted installation one
# person's house style must not become everybody's. Deleting the row is "back to the
# default", so nothing is ever lost by editing.
standards_pages = Table(
    "standards_pages",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("domain", String(64), nullable=False),
    Column("name", String(128), nullable=False),
    Column("body", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("standards_pages_owner", "owner_id", "domain", "name", unique=True),
)

standards_chunks = Table(
    "standards_chunks",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("scope", Text, nullable=False),  # default | user | project
    Column("project_id", String(64)),
    # set on the `user` scope: whose rewritten pages these sections came from
    Column("owner_id", String(64)),
    Column("domain", Text, nullable=False),
    Column("page", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("heading", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("tags", Text, nullable=False),
    Column("embedder", Text, nullable=False),
    Column("embedding", LargeBinary),
    # the section's position in its page, so `browse` returns them as they were written.
    # SQLite's implicit rowid used to serve this; an explicit column travels.
    Column("seq", Integer, nullable=False, server_default="0"),
    Index("standards_chunks_domain", "domain", "scope", "project_id"),
)

# One fingerprint per scope; a corpus whose files have not moved is not reindexed.
standards_fingerprints = Table(
    "standards_fingerprints",
    metadata,
    Column("scope_key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)


__all__ = [
    "agent_members",
    "api_tokens",
    "email_outbox",
    "email_tokens",
    "job_history",
    "jobs",
    "metadata",
    "model_prices",
    "project_briefs",
    "projects",
    "rate_limits",
    "sessions",
    "settings",
    "standards_chunks",
    "standards_fingerprints",
    "standards_pages",
    "support_requests",
    "test_runs",
    "translations",
    "users",
]
