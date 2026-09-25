"""email identity: signup, verification and password reset

Adds the address a person signs up with, the one-shot links that prove it or reset a
password, the outbox those links land in when no SMTP is configured, and the counters
that ration all of it.

Existing accounts keep working. Their ``email`` is null, which ``User.verified`` reads as
"made before signup existed, nothing to prove": they go on logging in by username until
somebody gives them an address.

Revision ID: 0002_email_identity
Revises: 0001_baseline
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_email_identity"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email", sa.String(320)))
        batch.add_column(sa.Column("email_verified_at", sa.Text()))
        batch.add_column(sa.Column("status", sa.Text(), server_default="active"))
        batch.create_unique_constraint("users_email", ["email"])
    op.execute("UPDATE users SET status = 'active' WHERE status IS NULL")

    op.create_table(
        "email_tokens",
        sa.Column("token_hash", sa.String(128), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("used_at", sa.Text()),
    )
    op.create_index("email_tokens_user", "email_tokens", ["user_id", "kind"])

    op.create_table(
        "rate_limits",
        sa.Column("bucket", sa.String(255), primary_key=True),
        sa.Column("window_start", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "email_outbox",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("to_address", sa.String(320), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("email_outbox")
    op.drop_table("rate_limits")
    op.drop_index("email_tokens_user", table_name="email_tokens")
    op.drop_table("email_tokens")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("users_email", type_="unique")
        batch.drop_column("status")
        batch.drop_column("email_verified_at")
        batch.drop_column("email")
