"""machine about: what a lent machine says it is

One nullable column. A release before this one never reads it, so a rollback opens the
database unchanged; a machine that never says leaves it empty and is drawn by its
capabilities, as before.

Revision ID: 0016_machine_about
Revises: 0015_machines_write
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_machine_about"
down_revision: str | None = "0015_machines_write"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workers") as batch:
        batch.add_column(sa.Column("about_json", sa.Text))


def downgrade() -> None:
    with op.batch_alter_table("workers") as batch:
        batch.drop_column("about_json")
