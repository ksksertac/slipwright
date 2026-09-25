"""support requests: what somebody wrote on the support page

One row per request. The letter goes out the moment it is written, but a mail server
that is down must not lose the question, so the row is written first and ``delivery``
records where the letter ended up -- sent, parked in the outbox, or refused.

Revision ID: 0005_support
Revises: 0004_per_user_settings
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_support"
down_revision: str | None = "0004_per_user_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64)),
        sa.Column("name", sa.Text, nullable=False, server_default=""),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("category", sa.Text, nullable=False, server_default="other"),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("delivery", sa.Text, nullable=False, server_default="outbox"),
        sa.Column("delivery_error", sa.Text),
        sa.Column("sent_to", sa.String(320)),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("closed_at", sa.Text),
    )
    op.create_index("support_requests_user", "support_requests", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("support_requests_user", table_name="support_requests")
    op.drop_table("support_requests")
