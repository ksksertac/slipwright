"""Standards pages as one account rewrote them, mixed into ``JobStore``.

The pages Slipwright ships are files in the package and stay exactly as they are. When
somebody edits one, the edited copy is written here under their own account and shadows
the shipped page *for them alone*. Deleting the row is "back to the default", so an edit
is never destructive and never has to be undone by hand.

This replaces the older arrangement, where editing a standard rewrote the file in the
server's own source tree and committed it to a branch. That is right for one team on one
machine and wrong for a server: there, one person's house style would silently become
everybody's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from slipwright.schemas.job import new_job_id, utcnow
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import standards_pages


class PageStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    def user_pages(self, owner_id: str, domain: str | None = None) -> list[dict[str, Any]]:
        """Every page this account has its own version of, in reading order."""
        query = (
            select(standards_pages)
            .where(standards_pages.c.owner_id == owner_id)
            .order_by(standards_pages.c.domain, standards_pages.c.name)
        )
        if domain:
            query = query.where(standards_pages.c.domain == domain)
        with self.db.connect() as conn:
            return rows(conn.execute(query))

    def get_user_page(self, owner_id: str, domain: str, name: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            return one(
                conn.execute(
                    select(standards_pages).where(
                        standards_pages.c.owner_id == owner_id,
                        standards_pages.c.domain == domain,
                        standards_pages.c.name == name,
                    )
                )
            )

    def save_user_page(self, owner_id: str, domain: str, name: str, body: str) -> dict[str, Any]:
        with self.db.begin() as conn:
            conn.execute(
                self.db.upsert(
                    standards_pages,
                    {
                        "id": new_job_id(),
                        "owner_id": owner_id,
                        "domain": domain,
                        "name": name,
                        "body": body,
                        "updated_at": utcnow().isoformat(),
                    },
                    key=["owner_id", "domain", "name"],
                    update=["body", "updated_at"],
                )
            )
        page = self.get_user_page(owner_id, domain, name)
        assert page is not None
        return page

    def delete_user_page(self, owner_id: str, domain: str, name: str) -> bool:
        """Drop this account's version. ``True`` when there was one: the page goes back to
        the one Slipwright ships."""
        with self.db.begin() as conn:
            gone = conn.execute(
                delete(standards_pages).where(
                    standards_pages.c.owner_id == owner_id,
                    standards_pages.c.domain == domain,
                    standards_pages.c.name == name,
                )
            )
        return bool(gone.rowcount)

    def pages_fingerprint(self, owner_id: str) -> str:
        """Cheap change detector over an account's pages, so the index is not rebuilt
        when nothing has moved. Mirrors ``corpus_fingerprint`` over files."""
        import hashlib

        parts = [
            f"{p['domain']}/{p['name']}:{p['updated_at']}:{len(p['body'])}"
            for p in self.user_pages(owner_id)
        ]
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def forget_pages(self, owner_id: str) -> None:
        """Everything this account rewrote. Part of deleting it."""
        with self.db.begin() as conn:
            conn.execute(delete(standards_pages).where(standards_pages.c.owner_id == owner_id))


def as_page(row: dict[str, Any]) -> dict[str, Any]:
    """A stored row in the shape ``load_corpus`` hands out, so the two mix freely."""
    return {
        "domain": row["domain"],
        "name": row["name"],
        "body": row["body"],
        "updated_at": datetime.fromisoformat(row["updated_at"]),
    }


__all__ = ["PageStoreMixin", "as_page"]
