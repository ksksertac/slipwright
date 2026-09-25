"""standards in three layers: what ships, what an account rewrote, what a repo overrides

Editing a standards page used to rewrite the file in the server's own source tree and
commit it to a branch, which on a hosted installation would make one person's house style
everybody's. A rewritten page is now a row against an account, and shadows the shipped
page for that account alone.

The index gains the layer it belongs to. It is derived data, rebuilt from its sources
whenever the fingerprint moves, so the existing rows are simply dropped rather than
migrated: the next read puts them back.

Revision ID: 0005_standards_layers
Revises: 0004_per_user_settings
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_standards_layers"
down_revision: str | None = "0004_per_user_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "standards_pages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "standards_pages_owner", "standards_pages", ["owner_id", "domain", "name"], unique=True
    )

    with op.batch_alter_table("standards_chunks") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(64)))
    # the index is a cache of the corpus; emptying it costs one reindex and nothing else
    op.execute("DELETE FROM standards_chunks")
    op.execute("DELETE FROM standards_fingerprints")


def downgrade() -> None:
    op.execute("DELETE FROM standards_chunks")
    op.execute("DELETE FROM standards_fingerprints")
    with op.batch_alter_table("standards_chunks") as batch:
        batch.drop_column("owner_id")
    op.drop_index("standards_pages_owner", table_name="standards_pages")
    op.drop_table("standards_pages")
