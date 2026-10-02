"""history detail size: how long an entry's detail is, kept beside it

A development's page asks for it every time anything happens, and the diffs and logs in
its history are most of its bytes -- one entry once carried a 145 MB diff. The page is
now sent each entry's size instead of its detail, and fetches the one somebody opens.
SQLite loads a value whole even to take its length, so the size is a column of its own,
filled here once for the entries already written.

A nullable column the release before this one never reads: a rollback opens the
database unchanged.

Revision ID: 0014_history_detail_size
Revises: 0013_job_messages
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_history_detail_size"
down_revision: str | None = "0013_job_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_history") as batch:
        batch.add_column(sa.Column("detail_size", sa.Integer))
    history = sa.table(
        "job_history", sa.column("detail", sa.Text), sa.column("detail_size", sa.Integer)
    )
    op.get_bind().execute(
        sa.update(history)
        .where(history.c.detail.is_not(None))
        .values(detail_size=sa.func.length(history.c.detail))
    )


def downgrade() -> None:
    with op.batch_alter_table("job_history") as batch:
        batch.drop_column("detail_size")
