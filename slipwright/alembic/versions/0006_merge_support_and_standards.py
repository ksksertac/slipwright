"""the two lines of work that started from 0004 become one again

``0005_support`` (the support requests table) and ``0005_standards_layers`` (standards
against an account) were both written on top of ``0004_per_user_settings``, which leaves
the history with two heads. Alembic refuses to upgrade or stamp "head" while that is
true, so no database can be brought up to date and a fresh one cannot be created at all.

This revision revises both and adds nothing of its own: it is the join, not a change.

Revision ID: 0006_merge_support_and_standards
Revises: 0005_support, 0005_standards_layers
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0006_merge_support_and_standards"
down_revision: tuple[str, ...] = ("0005_support", "0005_standards_layers")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing: both parents already did their own work."""


def downgrade() -> None:
    """Nothing: splitting back into two heads is what the parents' own downgrades do."""
