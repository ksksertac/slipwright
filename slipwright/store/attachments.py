"""Attachments, mixed into ``JobStore``.

Every read takes ``owner_id`` like the rest of the store: an attachment of somebody
else's is *not found*. The file's bytes are only ever read by ``attachment_data``; every
other read leaves the ``data`` column out, because a project's list of fifty PDFs is
fifty rows, not two gigabytes.
"""

from __future__ import annotations

import builtins
import hashlib
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, insert, select, update

from slipwright.events import EventBus
from slipwright.schemas.attachment import Attachment, Reading, ReadingState, Scope
from slipwright.schemas.job import new_job_id, utcnow
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import attachments

#: See ``slipwright.store.sqlite.ANY_OWNER``; repeated here so the mixin needs no import
#: of the class it is mixed into.
_ANY = "*"

# everything but the file and its text: what a list, an event or a page needs
_LISTED = [c for c in attachments.c if c.name not in {"data", "text"}]


class AttachmentNotFound(KeyError):
    def __init__(self, attachment_id: str) -> None:
        super().__init__(attachment_id)
        self.attachment_id = attachment_id

    def __str__(self) -> str:
        return f"attachment not found: {self.attachment_id}"


def _attachment(row: dict[str, Any], text_chars: int) -> Attachment:
    reading = row.get("reading_json")
    return Attachment(
        id=row["id"],
        project_id=row["project_id"],
        job_id=row["job_id"],
        scope=row["scope"],
        name=row["name"],
        media_type=row["media_type"],
        size=row["size"],
        pages=row["pages"],
        text_chars=text_chars,
        reading_state=row["reading_state"],
        reading=Reading.model_validate_json(reading) if reading else None,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class AttachmentStoreMixin:
    """Requires ``db`` and ``events`` on the host class."""

    db: Database
    events: EventBus

    def _listed(self) -> Any:
        return select(*_LISTED, func.length(attachments.c.text).label("text_chars"))

    def add_attachment(
        self,
        *,
        project_id: str,
        owner_id: str | None,
        name: str,
        media_type: str,
        data: bytes,
        text: str,
        pages: int,
        scope: Scope,
    ) -> Attachment:
        attachment_id = new_job_id()
        row = {
            "id": attachment_id,
            "owner_id": owner_id,
            "project_id": project_id,
            "job_id": None,
            "scope": scope,
            "name": name,
            "media_type": media_type,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "pages": pages,
            "data": data,
            "text": text,
            "reading_state": "pending",
            "reading_json": None,
            "created_at": utcnow().isoformat(),
        }
        with self.db.begin() as conn:
            conn.execute(insert(attachments).values(**row))
        self._announce(project_id, owner_id, attachment_id, "added")
        return self.get_attachment(attachment_id)

    def get_attachment(self, attachment_id: str, owner_id: str | None = _ANY) -> Attachment:
        query = self._listed().where(attachments.c.id == attachment_id)
        if owner_id != _ANY:
            query = query.where(attachments.c.owner_id == owner_id)
        with self.db.connect() as conn:
            row = one(conn.execute(query))
        if row is None:
            raise AttachmentNotFound(attachment_id)
        return _attachment(row, row["text_chars"] or 0)

    def attachment_data(
        self, attachment_id: str, owner_id: str | None = _ANY
    ) -> tuple[Attachment, bytes]:
        found = self.get_attachment(attachment_id, owner_id)
        with self.db.connect() as conn:
            data = conn.execute(
                select(attachments.c.data).where(attachments.c.id == attachment_id)
            ).scalar_one()
        return found, bytes(data)

    def attachment_text(self, attachment_id: str) -> str:
        with self.db.connect() as conn:
            text = conn.execute(
                select(attachments.c.text).where(attachments.c.id == attachment_id)
            ).scalar_one_or_none()
        return str(text or "")

    def list_attachments(
        self,
        project_id: str,
        owner_id: str | None = _ANY,
        *,
        job_id: str | None = None,
        scopes: Iterable[Scope] = ("project", "job"),
    ) -> builtins.list[Attachment]:
        """Oldest first, the order they were given in.

        ``job_id`` narrows the ``job`` scope to one development's files; the project's
        own always come with them, because every development reads those."""
        wanted = set(scopes)
        query = self._listed().where(
            attachments.c.project_id == project_id, attachments.c.scope.in_(wanted)
        )
        if job_id is not None:
            query = query.where(
                (attachments.c.scope != "job") | (attachments.c.job_id == job_id)
            )
        if owner_id != _ANY:
            query = query.where(attachments.c.owner_id == owner_id)
        query = query.order_by(attachments.c.created_at, attachments.c.id)
        with self.db.connect() as conn:
            return [_attachment(r, r["text_chars"] or 0) for r in rows(conn.execute(query))]

    def count_attachments(self, project_id: str) -> int:
        """Drafts count too: they are files taking room like any other."""
        with self.db.connect() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(attachments)
                    .where(attachments.c.project_id == project_id)
                ).scalar_one()
            )

    def attachment_bytes(self, owner_id: str | None) -> int:
        """What one account's files take, for its disk quota."""
        query = select(func.coalesce(func.sum(attachments.c.size), 0))
        if owner_id != _ANY:
            query = query.where(attachments.c.owner_id == owner_id)
        with self.db.connect() as conn:
            return int(conn.execute(query).scalar_one())

    def claim_drafts(
        self, project_id: str, ids: builtins.list[str], job_id: str, owner_id: str | None = _ANY
    ) -> None:
        """Hand the files chosen on the new-development form to the development.

        Checked before anything moves: an id that is not a draft of this project -- a
        file of another project, somebody else's, one already sent -- refuses the whole
        claim, rather than starting the development with half of what was chosen."""
        if not ids:
            return
        wanted = set(ids)
        query = select(attachments.c.id).where(
            attachments.c.id.in_(wanted),
            attachments.c.project_id == project_id,
            attachments.c.scope == "draft",
        )
        if owner_id != _ANY:
            query = query.where(attachments.c.owner_id == owner_id)
        with self.db.begin() as conn:
            found = {r["id"] for r in rows(conn.execute(query))}
            missing = wanted - found
            if missing:
                raise AttachmentNotFound(sorted(missing)[0])
            conn.execute(
                update(attachments)
                .where(attachments.c.id.in_(wanted))
                .values(scope="job", job_id=job_id)
            )

    def set_reading(
        self, attachment_id: str, state: ReadingState, reading: Reading | None = None
    ) -> Attachment:
        values: dict[str, Any] = {"reading_state": state}
        if reading is not None:
            values["reading_json"] = reading.model_dump_json()
        with self.db.begin() as conn:
            changed = conn.execute(
                update(attachments).where(attachments.c.id == attachment_id).values(**values)
            )
            if changed.rowcount == 0:
                raise AttachmentNotFound(attachment_id)
        found = self.get_attachment(attachment_id)
        self._announce(found.project_id, self._attachment_owner(attachment_id), found.id, state)
        return found

    def delete_attachment(self, attachment_id: str, owner_id: str | None = _ANY) -> None:
        found = self.get_attachment(attachment_id, owner_id)
        owner = self._attachment_owner(attachment_id)
        with self.db.begin() as conn:
            conn.execute(delete(attachments).where(attachments.c.id == attachment_id))
        self._announce(found.project_id, owner, attachment_id, "deleted")

    def forget_drafts(self, project_id: str, older_than: timedelta) -> int:
        """Drafts nobody sent: a form filled in and walked away from. Nothing reads them,
        so after a while they are only taking room."""
        cutoff = (utcnow() - older_than).isoformat()
        with self.db.begin() as conn:
            gone = conn.execute(
                delete(attachments).where(
                    attachments.c.project_id == project_id,
                    attachments.c.scope == "draft",
                    attachments.c.created_at < cutoff,
                )
            )
        return int(gone.rowcount or 0)

    def _attachment_owner(self, attachment_id: str) -> str | None:
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(attachments.c.owner_id).where(attachments.c.id == attachment_id)
                )
            )
        return None if row is None else row["owner_id"]

    def _announce(
        self, project_id: str, owner_id: str | None, attachment_id: str, action: str
    ) -> None:
        self.events.emit(
            "attachment",
            project_id=project_id,
            owner_id=owner_id,
            payload={"id": attachment_id, "action": action},
        )


__all__ = ["AttachmentNotFound", "AttachmentStoreMixin"]
