"""notify: agents reach people in Telegram, Slack, Discord and Teams

Three new tables and nothing rewritten. ``chat_links`` is a person's proven account on a
chat service, ``chat_codes`` the one-time codes that prove it, and ``chat_prompts`` the
"carry on or reject?" questions sent to one person, so a button pressed later can be
checked against the gate it was about.

Revision ID: 0008_notify
Revises: 0007_teams
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_notify"
down_revision: str | None = "0007_teams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("address_json", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False, server_default=""),
        sa.Column("linked_at", sa.Text, nullable=False),
    )
    op.create_index(
        "chat_links_person", "chat_links", ["owner_id", "channel", "user_id"], unique=True
    )
    op.create_index("chat_links_external", "chat_links", ["owner_id", "channel", "external_id"])
    op.create_table(
        "chat_codes",
        sa.Column("code_hash", sa.String(128), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
    )
    op.create_table(
        "chat_prompts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("marker", sa.Text, nullable=False),
        sa.Column("address_json", sa.Text, nullable=False),
        sa.Column("ref_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("decided_at", sa.Text),
    )
    op.create_index("chat_prompts_job", "chat_prompts", ["job_id", "status"])
    op.create_index(
        "chat_prompts_person",
        "chat_prompts",
        ["owner_id", "channel", "external_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("chat_prompts_person", table_name="chat_prompts")
    op.drop_index("chat_prompts_job", table_name="chat_prompts")
    op.drop_table("chat_prompts")
    op.drop_table("chat_codes")
    op.drop_index("chat_links_external", table_name="chat_links")
    op.drop_index("chat_links_person", table_name="chat_links")
    op.drop_table("chat_links")
