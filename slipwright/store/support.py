"""Support requests, mixed into ``JobStore``.

A request is written before any letter is attempted, so a mail server that is refusing
connections costs the sender a notification, not the question itself. ``delivery`` is
filled in afterwards by whoever tried to send it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import insert, select, update

from slipwright.auth import normalise_email
from slipwright.schemas.job import new_job_id, utcnow
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import support_requests


class SupportRequestNotFound(KeyError):
    def __init__(self, request_id: str) -> None:
        super().__init__(request_id)
        self.request_id = request_id

    def __str__(self) -> str:
        return f"support request not found: {self.request_id}"


class SupportStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    def create_support_request(
        self,
        *,
        email: str,
        subject: str,
        message: str,
        user_id: str | None = None,
        name: str = "",
        category: str = "other",
    ) -> dict[str, Any]:
        """Write the request. Delivery is recorded separately, once it has been tried."""
        subject = subject.strip()
        message = message.strip()
        if not subject:
            raise ValueError("a support request needs a subject")
        if not message:
            raise ValueError("a support request needs a message")
        row = {
            "id": new_job_id(),
            "user_id": user_id,
            "name": name.strip(),
            "email": normalise_email(email),
            "category": category or "other",
            "subject": subject,
            "message": message,
            "delivery": "pending",
            "delivery_error": None,
            "sent_to": None,
            "status": "open",
            "created_at": utcnow().isoformat(),
            "closed_at": None,
        }
        with self.db.begin() as conn:
            conn.execute(insert(support_requests).values(**row))
        return row

    def record_support_delivery(
        self,
        request_id: str,
        *,
        delivery: str,
        sent_to: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Say where the letter ended up: ``sent``, ``outbox`` or ``failed``."""
        with self.db.begin() as conn:
            changed = conn.execute(
                update(support_requests)
                .where(support_requests.c.id == request_id)
                .values(delivery=delivery, sent_to=sent_to, delivery_error=error)
            )
            if changed.rowcount == 0:
                raise SupportRequestNotFound(request_id)
        return self.get_support_request(request_id)

    def set_support_status(self, request_id: str, status: str) -> dict[str, Any]:
        """``open`` or ``closed``. Nothing closes a request on its own."""
        if status not in {"open", "closed"}:
            raise ValueError(f"unknown support status: {status}")
        with self.db.begin() as conn:
            changed = conn.execute(
                update(support_requests)
                .where(support_requests.c.id == request_id)
                .values(
                    status=status,
                    closed_at=utcnow().isoformat() if status == "closed" else None,
                )
            )
            if changed.rowcount == 0:
                raise SupportRequestNotFound(request_id)
        return self.get_support_request(request_id)

    def get_support_request(self, request_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = one(
                conn.execute(select(support_requests).where(support_requests.c.id == request_id))
            )
        if row is None:
            raise SupportRequestNotFound(request_id)
        return row

    def list_support_requests(
        self, *, user_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Newest first. ``user_id`` narrows it to one person's own requests."""
        query = select(support_requests).order_by(support_requests.c.created_at.desc()).limit(limit)
        if user_id is not None:
            query = query.where(support_requests.c.user_id == user_id)
        with self.db.connect() as conn:
            return rows(conn.execute(query))


__all__ = ["SupportRequestNotFound", "SupportStoreMixin"]
