"""job title: the short name a development is shown by

A development was shown everywhere by its whole request -- a paragraph in the table, the
dashboard, every chat message. It gets a name of its own, asked for when it is started.
The developments already made are given one here, from the first sentence of what was
asked, so that no list goes back to showing paragraphs for them.

Revision ID: 0011_job_title
Revises: 0010_attachments
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_job_title"
down_revision: str | None = "0010_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIMIT = 80


def _headline(request: str) -> str:
    # a copy of ``schemas.job.headline`` as it stood: a migration runs the rule of its own
    # day, not whatever the application's has become since
    first = request.strip().splitlines()[0] if request.strip() else ""
    for stop in (". ", "? ", "! "):
        if stop in first:
            first = first.split(stop, 1)[0]
    first = first.strip().rstrip(".!?")
    if len(first) <= LIMIT:
        return first
    clipped = first[: LIMIT - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return f"{clipped or first[: LIMIT - 1]}…"


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("title", sa.Text, nullable=False, server_default=""))
    jobs = sa.table(
        "jobs", sa.column("id", sa.String), sa.column("request", sa.Text), sa.column("title")
    )
    conn = op.get_bind()
    for job_id, request in conn.execute(sa.select(jobs.c.id, jobs.c.request)).all():
        conn.execute(
            sa.update(jobs).where(jobs.c.id == job_id).values(title=_headline(request or ""))
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("title")
