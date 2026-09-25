"""baseline: the schema as it stood when migrations began

A database created before this point already has these tables; it is stamped with this
revision rather than having it applied. A database created after it is built straight
from the declarations in ``store/schema.py`` and stamped too. The revision therefore
exists to be a starting point, not to be run -- which is why ``upgrade`` is careful to
create only what is missing.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from slipwright.store.schema import metadata

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    metadata.drop_all(op.get_bind(), checkfirst=True)
