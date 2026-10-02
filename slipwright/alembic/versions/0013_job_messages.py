"""job messages: what a person says to a development's agents, in a table of its own

The steering inbox lived inside a job's ``data_json``, which the run loop rewrites whole
from the copy it holds -- so a message sent while a phase was being built could be
overwritten by the loop's next save. The messages already there are copied across; the
copy in ``data_json`` is left where it is, which the release before this one still reads.

Revision ID: 0013_job_messages
Revises: 0012_workers
Create Date: 2026-10-02
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_job_messages"
down_revision: str | None = "0012_workers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("by", sa.Text),
        sa.Column("at", sa.Text, nullable=False),
        sa.Column("step", sa.String(64)),
        sa.Column("phase", sa.Integer),
        sa.Column("role", sa.String(32)),
        sa.Column("reply_to", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("answer", sa.Text),
        sa.Column("change", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("answered_at", sa.Text),
        sa.Column("consumed_at", sa.Text),
        sa.Column("consumed_by", sa.String(32)),
        sa.Column("cost_json", sa.Text),
        sa.Column("billed", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("job_messages_job", "job_messages", ["job_id", "at"])
    jobs = sa.table("jobs", sa.column("id", sa.String), sa.column("data_json", sa.Text))
    messages = sa.table(
        "job_messages",
        sa.column("id"),
        sa.column("job_id"),
        sa.column("kind"),
        sa.column("text"),
        sa.column("at"),
        sa.column("status"),
        sa.column("consumed_at"),
        sa.column("consumed_by"),
    )
    conn = op.get_bind()
    for job_id, data_json in conn.execute(sa.select(jobs.c.id, jobs.c.data_json)).all():
        try:
            inbox = (json.loads(data_json or "{}") or {}).get("inbox") or []
        except ValueError:
            continue
        for m in inbox:
            if not isinstance(m, dict) or not m.get("id") or not m.get("text"):
                continue
            conn.execute(
                sa.insert(messages).values(
                    id=m["id"],
                    job_id=job_id,
                    kind="steer",
                    text=m["text"],
                    at=m.get("at") or "",
                    status="read" if m.get("consumed_at") else "pending",
                    consumed_at=m.get("consumed_at"),
                    consumed_by=m.get("consumed_by"),
                )
            )


def downgrade() -> None:
    op.drop_index("job_messages_job", table_name="job_messages")
    op.drop_table("job_messages")
