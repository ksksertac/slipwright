"""teams: an account can put people on its agents

An account used to be alone: whoever signed up owned the projects and was the only person
who could approve anything. This adds the other kind of account -- somebody invited onto
one agent -- and the table that records who is on what.

Two changes, both additive. ``users.owner_id`` says which account a person belongs to
(null for everybody who came before, because everybody who came before is their own), and
``agent_members`` holds one row per (account, agent, person) with how it started and how
it ended. Nothing is rewritten, so an installation upgrades without noticing.

Revision ID: 0007_teams
Revises: 0006_merge_support_and_standards
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_teams"
down_revision: str | None = "0006_merge_support_and_standards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(64)))
    op.create_table(
        "agent_members",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="invited"),
        sa.Column("invited_by", sa.String(64)),
        sa.Column("invited_at", sa.Text, nullable=False),
        sa.Column("responded_at", sa.Text),
        sa.Column("ended_at", sa.Text),
    )
    op.create_index("agent_members_owner", "agent_members", ["owner_id", "role"])
    op.create_index("agent_members_user", "agent_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("agent_members_user", table_name="agent_members")
    op.drop_index("agent_members_owner", table_name="agent_members")
    op.drop_table("agent_members")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("owner_id")
