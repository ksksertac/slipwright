"""workers: machines an account lends its developments, and the builds they are asked for

Three new tables and nothing rewritten. A development that never names an iOS or an
Android phase never touches any of them, and a database from before this has none to
fill, so a release that meets it is unchanged by it.

Revision ID: 0011_workers
Revises: 0010_attachments
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_workers"
down_revision: str | None = "0010_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("capabilities_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("paired_at", sa.Text, nullable=False),
        sa.Column("last_seen_at", sa.Text),
        sa.Column("revoked_at", sa.Text),
    )
    op.create_index("workers_owner", "workers", ["owner_id"])
    op.create_table(
        "worker_codes",
        sa.Column("code_hash", sa.String(128), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
    )
    op.create_table(
        "worker_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("commands_json", sa.Text, nullable=False),
        sa.Column("timeout_s", sa.Float, nullable=False),
        sa.Column("snapshot", sa.LargeBinary, nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("worker_id", sa.String(64)),
        sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("exit_code", sa.Integer),
        sa.Column("output", sa.Text),
        sa.Column("seconds", sa.Float),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("claimed_at", sa.Text),
        sa.Column("finished_at", sa.Text),
    )
    op.create_index("worker_tasks_queue", "worker_tasks", ["owner_id", "state", "created_at"])
    op.create_index("worker_tasks_job", "worker_tasks", ["job_id"])


def downgrade() -> None:
    op.drop_index("worker_tasks_job", table_name="worker_tasks")
    op.drop_index("worker_tasks_queue", table_name="worker_tasks")
    op.drop_table("worker_tasks")
    op.drop_table("worker_codes")
    op.drop_index("workers_owner", table_name="workers")
    op.drop_table("workers")
