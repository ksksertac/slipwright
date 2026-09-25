"""per-user settings: model keys, Git tokens and Jira belong to an account

The settings table had one row per name for the whole installation, which is why one
person's API key paid for another person's work. It now has one row per (account, name).

Existing rows are handed to the first administrator: on a single-team installation that
is exactly who they belonged to, and the alternative -- leaving them installation-wide --
would keep the leak alive. The settings that really are the installation's (mail, prices,
webhooks, and the flags the standards index runs on) are moved back afterwards.

Revision ID: 0004_per_user_settings
Revises: 0003_ownership
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_per_user_settings"
down_revision: str | None = "0003_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Named exactly, or by the prefix before the first dot. These stay with the server.
INSTALLATION_KEYS = ("standards", "prices", "notifications", "mail")


def upgrade() -> None:
    conn = op.get_bind()
    first_admin = conn.execute(
        sa.text("SELECT id FROM users WHERE is_admin = 1 ORDER BY created_at, id LIMIT 1")
    ).scalar()

    # the primary key becomes (user_id, name), which SQLite can only do by rewriting.
    # The table predates the naming convention, so its primary key is anonymous in the
    # schema SQLite reflects; the convention gives it the name ``drop_constraint`` needs.
    with op.batch_alter_table(
        "settings", recreate="always", naming_convention={"pk": "pk_%(table_name)s"}
    ) as batch:
        batch.add_column(sa.Column("user_id", sa.String(64), nullable=False, server_default=""))
        batch.drop_constraint("pk_settings", type_="primary")
        batch.create_primary_key("pk_settings", ["user_id", "name"])

    if first_admin is None:
        return
    conn.execute(
        sa.text("UPDATE settings SET user_id = :owner WHERE user_id = ''"),
        {"owner": first_admin},
    )
    # ... except the ones that were never personal
    for key in INSTALLATION_KEYS:
        conn.execute(
            sa.text(
                "UPDATE settings SET user_id = '' WHERE name = :exact OR name LIKE :prefix"
            ),
            {"exact": key, "prefix": f"{key}.%"},
        )


def downgrade() -> None:
    conn = op.get_bind()
    # collapse back to one row per name, keeping whichever was written last
    conn.execute(
        sa.text(
            "DELETE FROM settings WHERE rowid NOT IN "
            "(SELECT MAX(rowid) FROM settings GROUP BY name)"
        )
    )
    with op.batch_alter_table("settings", recreate="always") as batch:
        batch.drop_constraint("pk_settings", type_="primary")
        batch.create_primary_key("pk_settings", ["name"])
        batch.drop_column("user_id")
