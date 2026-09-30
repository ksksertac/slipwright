"""attachments: files a person gives the agents -- documents, screens, photos

One new table and nothing rewritten. The file itself is a column, so it moves with the
database and is owned like every other row; nothing about an existing project changes
until somebody attaches something to it.

Revision ID: 0010_attachments
Revises: 0009_two_factor
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_attachments"
down_revision: str | None = "0009_two_factor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64)),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(64)),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("reading_state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reading_json", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("attachments_project", "attachments", ["project_id", "scope", "created_at"])
    op.create_index("attachments_job", "attachments", ["job_id"])
    op.create_index("attachments_owner", "attachments", ["owner_id"])


def downgrade() -> None:
    op.drop_index("attachments_owner", table_name="attachments")
    op.drop_index("attachments_job", table_name="attachments")
    op.drop_index("attachments_project", table_name="attachments")
    op.drop_table("attachments")
