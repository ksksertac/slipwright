"""ownership: a project and its jobs belong to an account

Until now every logged-in person saw everything, which is right for one team on one
machine and wrong for a server strangers sign up to. Both tables gain an owner.

Existing rows are handed to the first administrator rather than left ownerless, so an
installation that upgrades keeps working exactly as it did for the person who runs it.
Where there is no administrator (a database with no users at all) the rows stay null,
which the store reads as "the installation's".

Revision ID: 0003_ownership
Revises: 0002_email_identity
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ownership"
down_revision: str | None = "0002_email_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(64)))
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(64)))
    op.create_index("projects_owner", "projects", ["owner_id", "created_at"])
    op.create_index("jobs_owner", "jobs", ["owner_id", "created_at"])

    conn = op.get_bind()
    first_admin = conn.execute(
        sa.text("SELECT id FROM users WHERE is_admin = 1 ORDER BY created_at, id LIMIT 1")
    ).scalar()
    if first_admin is None:
        return
    conn.execute(
        sa.text("UPDATE projects SET owner_id = :owner WHERE owner_id IS NULL"),
        {"owner": first_admin},
    )
    conn.execute(
        sa.text("UPDATE jobs SET owner_id = :owner WHERE owner_id IS NULL"),
        {"owner": first_admin},
    )
    # the owner also lives inside the project's JSON blob, which is what the API returns
    for row in conn.execute(sa.text("SELECT id, data_json FROM projects")).fetchall():
        import json

        payload = json.loads(row[1])
        if payload.get("owner_id") is None:
            payload["owner_id"] = first_admin
            conn.execute(
                sa.text("UPDATE projects SET data_json = :data WHERE id = :id"),
                {"data": json.dumps(payload), "id": row[0]},
            )


def downgrade() -> None:
    op.drop_index("jobs_owner", table_name="jobs")
    op.drop_index("projects_owner", table_name="projects")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("owner_id")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("owner_id")
