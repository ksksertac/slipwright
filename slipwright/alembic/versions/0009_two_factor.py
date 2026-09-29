"""two-factor: a code from an authenticator app after the password, for whoever wants it

Four nullable columns on ``users`` and nothing rewritten: every account that exists comes
through with two-step sign-in off, which is what it had. ``totp_secret`` is encrypted with
the installation key; it is set when somebody starts setting it up and only counts once
``totp_enabled_at`` is, so a setup abandoned half way changes nothing about signing in.

Revision ID: 0009_two_factor
Revises: 0008_notify
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_two_factor"
down_revision: str | None = "0008_notify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("totp_secret", sa.Text()))
        batch.add_column(sa.Column("totp_enabled_at", sa.Text()))
        batch.add_column(sa.Column("totp_last_step", sa.Integer()))
        batch.add_column(sa.Column("totp_recovery", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("totp_recovery")
        batch.drop_column("totp_last_step")
        batch.drop_column("totp_enabled_at")
        batch.drop_column("totp_secret")
