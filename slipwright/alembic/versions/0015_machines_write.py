"""machines write: the calls a lent machine makes on its own plan, and who lent it

One new table and three nullable columns. A release before this one never reads any of
them, so a rollback opens the database unchanged; a machine paired before it has no
``lent_by`` and is the owner's, which is what it was.

Revision ID: 0015_machines_write
Revises: 0014_history_detail_size
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_machines_write"
down_revision: str | None = "0014_history_detail_size"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workers") as batch:
        batch.add_column(sa.Column("lent_by", sa.String(64)))
    with op.batch_alter_table("worker_codes") as batch:
        batch.add_column(sa.Column("lent_by", sa.String(64)))
        batch.add_column(sa.Column("pair_key", sa.String(128)))
    op.create_table(
        "worker_calls",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("phase", sa.Integer),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("domain", sa.String(16), nullable=False),
        sa.Column("request_json", sa.Text, nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("worker_id", sa.String(64)),
        sa.Column("progress", sa.Text),
        sa.Column("answer", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("error_kind", sa.String(16)),
        sa.Column("seconds", sa.Float),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("claimed_at", sa.Text),
        sa.Column("heard_at", sa.Text),
        sa.Column("finished_at", sa.Text),
    )
    op.create_index("worker_calls_queue", "worker_calls", ["owner_id", "state", "created_at"])
    op.create_index("worker_calls_job", "worker_calls", ["job_id"])


def downgrade() -> None:
    op.drop_index("worker_calls_job", table_name="worker_calls")
    op.drop_index("worker_calls_queue", table_name="worker_calls")
    op.drop_table("worker_calls")
    with op.batch_alter_table("worker_codes") as batch:
        batch.drop_column("pair_key")
        batch.drop_column("lent_by")
    with op.batch_alter_table("workers") as batch:
        batch.drop_column("lent_by")
