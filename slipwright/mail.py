"""Sending the two letters Slipwright writes: prove your address, and set a new password.

Deliberately small. SMTP is the only transport, because every provider speaks it and an
installation that has one already need not sign up for another. Credentials live in the
settings store like every other secret.

There is a second transport, ``outbox``, which writes the message to a table instead of
sending it. It is what the test suite reads, and what an installation with no SMTP
configured falls back to -- so a verification link is never silently lost, an
administrator can still fetch it, and nothing about signing up depends on mail working on
day one.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import delete, insert, select

from slipwright.schemas.job import new_job_id, utcnow
from slipwright.store.db import rows
from slipwright.store.schema import email_outbox

if TYPE_CHECKING:
    from slipwright.store import JobStore

log = logging.getLogger(__name__)

#: Kept so an administrator can still find a link that was written days ago, and bounded
#: so the table cannot grow without limit.
OUTBOX_KEEP = 200


class MailError(RuntimeError):
    """The message could not be handed over. Never raised past a request handler."""


@dataclass(frozen=True)
class MailSettings:
    """What ``Settings → Email`` holds. ``password`` is stored encrypted and never read
    back out to the page -- only ``password_set`` is."""

    transport: str = "outbox"  # smtp | outbox
    host: str = ""
    port: int = 587
    username: str = ""
    security: str = "starttls"  # starttls | ssl | none
    from_address: str = ""
    from_name: str = "Slipwright"
    base_url: str = ""  # what the links in the letters point at
    #: Where the support page sends what people write. Empty means "the administrators":
    #: see ``slipwright/support.py``, which falls back to their confirmed addresses so a
    #: question is never written into a void.
    support_email: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.transport == "smtp" and self.host and self.from_address)


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class OutboxMailer:
    """Writes to ``email_outbox``. The transport of the test suite and of a fresh install."""

    def __init__(self, store: JobStore) -> None:
        self.store = store

    def send(self, to: str, subject: str, body: str) -> None:
        with self.store.db.begin() as conn:
            conn.execute(
                insert(email_outbox).values(
                    id=new_job_id(),
                    to_address=to,
                    subject=subject,
                    body=body,
                    at=utcnow().isoformat(),
                )
            )
            keep = [
                r["id"]
                for r in rows(
                    conn.execute(
                        select(email_outbox.c.id)
                        .order_by(email_outbox.c.at.desc())
                        .limit(OUTBOX_KEEP)
                    )
                )
            ]
            if keep:
                conn.execute(delete(email_outbox).where(email_outbox.c.id.not_in(keep)))
        log.info("mail written to the outbox for %s: %s", to, subject)


class SmtpMailer:
    """A plain SMTP send. One connection per message: the volume is a handful a day."""

    def __init__(self, settings: MailSettings, password: str, *, timeout: float = 20.0) -> None:
        self.settings = settings
        self.password = password
        self.timeout = timeout

    def send(self, to: str, subject: str, body: str) -> None:
        cfg = self.settings
        message = EmailMessage()
        message["From"] = (
            f"{cfg.from_name} <{cfg.from_address}>" if cfg.from_name else cfg.from_address
        )
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            if cfg.security == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(
                    cfg.host, cfg.port, timeout=self.timeout, context=ssl.create_default_context()
                )
            else:
                server = smtplib.SMTP(cfg.host, cfg.port, timeout=self.timeout)
            with server:
                if cfg.security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                if cfg.username:
                    server.login(cfg.username, self.password)
                server.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError(f"could not send to {to}: {exc}") from exc


def read_outbox(store: JobStore, *, to: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """The most recent unsent letters, newest first. Used by the tests and by the admin
    page of an installation whose SMTP is not set up yet."""
    query = select(email_outbox).order_by(email_outbox.c.at.desc()).limit(limit)
    if to is not None:
        query = query.where(email_outbox.c.to_address == to.strip().lower())
    with store.db.connect() as conn:
        return rows(conn.execute(query))


__all__ = [
    "OUTBOX_KEEP",
    "MailError",
    "MailSettings",
    "Mailer",
    "OutboxMailer",
    "SmtpMailer",
    "read_outbox",
]
