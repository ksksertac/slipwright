"""What a person said to a development's agents: mixed into ``JobStore``.

Rows only. The engine decides who answers a question and when a steer is read; the one
rule kept here is that nothing a person wrote is ever lost to somebody else's write. A
job's inbox is read from this table and *added* to on a save, never replaced, so the run
loop saving the copy of a job it read an hour ago cannot take back a message sent since.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, insert, select, update

from slipwright.schemas.job import InboxMessage, JobMessage, utcnow
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import job_messages


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _message(row: dict[str, Any]) -> JobMessage:
    return JobMessage(
        id=row["id"],
        job_id=row["job_id"],
        kind=row["kind"],
        text=row["text"],
        by=row["by"],
        at=datetime.fromisoformat(row["at"]),
        step=row["step"],
        phase=row["phase"],
        role=row["role"],
        reply_to=row["reply_to"],
        status=row["status"],
        answer=row["answer"],
        change=row["change"],
        error=row["error"],
        answered_at=_when(row["answered_at"]),
        consumed_at=_when(row["consumed_at"]),
        consumed_by=row["consumed_by"],
    )


def _inbox_row(job_id: str, m: InboxMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "job_id": job_id,
        "kind": "steer",
        "text": m.text,
        "at": m.at.isoformat(),
        "phase": m.phase,
        "role": m.role,
        "status": "pending" if m.pending else "read",
        "consumed_at": None if m.consumed_at is None else m.consumed_at.isoformat(),
        "consumed_by": m.consumed_by,
    }


class MessageStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    # -- the inbox, as a job carries it -----------------------------------------------

    @staticmethod
    def _read_inbox(conn: Any, job_id: str) -> list[InboxMessage]:
        query = (
            select(job_messages)
            .where(and_(job_messages.c.job_id == job_id, job_messages.c.kind == "steer"))
            .order_by(job_messages.c.at, job_messages.c.id)
        )
        return [
            InboxMessage(
                id=r["id"],
                text=r["text"],
                at=datetime.fromisoformat(r["at"]),
                consumed_at=_when(r["consumed_at"]),
                consumed_by=r["consumed_by"],
                role=r["role"],
                phase=r["phase"],
            )
            for r in rows(conn.execute(query))
        ]

    @staticmethod
    def _merge_inbox(conn: Any, job_id: str, inbox: Iterable[InboxMessage]) -> None:
        """Add what the copy has that the table does not, and mark read what the copy
        read. Nothing is removed and nothing read is made unread: the copy may be older
        than the table, and the table is the one that is right."""
        known = {
            r["id"]: r["consumed_at"]
            for r in rows(
                conn.execute(
                    select(job_messages.c.id, job_messages.c.consumed_at).where(
                        job_messages.c.job_id == job_id
                    )
                )
            )
        }
        for m in inbox:
            if m.id not in known:
                conn.execute(insert(job_messages).values(_inbox_row(job_id, m)))
            elif m.consumed_at is not None and known[m.id] is None:
                conn.execute(
                    update(job_messages)
                    .where(job_messages.c.id == m.id)
                    .values(
                        status="read",
                        consumed_at=m.consumed_at.isoformat(),
                        consumed_by=m.consumed_by,
                    )
                )

    def inbox(self, job_id: str) -> list[InboxMessage]:
        """The job's steering messages as they stand now, whatever copy of it is held."""
        with self.db.connect() as conn:
            return self._read_inbox(conn, job_id)

    # -- every kind -------------------------------------------------------------------

    def add_message(self, message: JobMessage) -> JobMessage:
        with self.db.begin() as conn:
            conn.execute(
                insert(job_messages).values(
                    id=message.id,
                    job_id=message.job_id,
                    kind=message.kind,
                    text=message.text,
                    by=message.by,
                    at=message.at.isoformat(),
                    step=message.step,
                    phase=message.phase,
                    role=message.role,
                    reply_to=message.reply_to,
                    status=message.status,
                    answer=message.answer,
                    change=message.change,
                    error=message.error,
                )
            )
        return message

    def get_message(self, message_id: str) -> JobMessage | None:
        with self.db.connect() as conn:
            row = one(conn.execute(select(job_messages).where(job_messages.c.id == message_id)))
        return None if row is None else _message(row)

    def list_messages(
        self,
        job_id: str,
        *,
        step: str | None = None,
        kinds: Sequence[str] | None = None,
        status: str | None = None,
    ) -> list[JobMessage]:
        query = select(job_messages).where(job_messages.c.job_id == job_id)
        if step is not None:
            query = query.where(job_messages.c.step == step)
        if kinds is not None:
            query = query.where(job_messages.c.kind.in_(list(kinds)))
        if status is not None:
            query = query.where(job_messages.c.status == status)
        query = query.order_by(job_messages.c.at, job_messages.c.id)
        with self.db.connect() as conn:
            return [_message(r) for r in rows(conn.execute(query))]

    def answer_message(
        self,
        message_id: str,
        *,
        answer: str | None,
        change: str | None = None,
        error: str | None = None,
        cost: dict[str, Any] | None = None,
    ) -> JobMessage | None:
        """Write what came back for a question -- an answer, or why there is none --
        with what the call cost, for the run to add to the job's spend."""
        with self.db.begin() as conn:
            conn.execute(
                update(job_messages)
                .where(job_messages.c.id == message_id)
                .values(
                    status="failed" if error else "answered",
                    answer=answer,
                    change=change,
                    error=error,
                    answered_at=utcnow().isoformat(),
                    cost_json=None if cost is None else json.dumps(cost),
                    billed=0 if cost is not None else 1,
                )
            )
        return self.get_message(message_id)

    def set_message_status(self, message_id: str, status: str) -> None:
        with self.db.begin() as conn:
            conn.execute(
                update(job_messages).where(job_messages.c.id == message_id).values(status=status)
            )

    def unbilled_answers(self, job_id: str) -> list[tuple[str, dict[str, Any]]]:
        """The calls that answered questions on this job and are not in its spend yet."""
        query = select(job_messages.c.id, job_messages.c.cost_json).where(
            and_(job_messages.c.job_id == job_id, job_messages.c.billed == 0)
        )
        with self.db.connect() as conn:
            found = rows(conn.execute(query))
        return [(r["id"], json.loads(r["cost_json"])) for r in found if r["cost_json"]]

    def mark_billed(self, message_ids: Sequence[str]) -> None:
        if not message_ids:
            return
        with self.db.begin() as conn:
            conn.execute(
                update(job_messages)
                .where(job_messages.c.id.in_(list(message_ids)))
                .values(billed=1)
            )

    def fail_unanswered(self, why: str) -> int:
        """Questions whose answer was being written when the process stopped: nothing will
        write it now, and one left 'answering' would say so forever."""
        with self.db.begin() as conn:
            result = conn.execute(
                update(job_messages)
                .where(
                    and_(job_messages.c.kind == "question", job_messages.c.status == "answering")
                )
                .values(status="failed", error=why, answered_at=utcnow().isoformat(), billed=1)
            )
        return int(result.rowcount or 0)
