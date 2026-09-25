"""The support desk: what somebody writes on the support page, and where it goes.

Three things happen, in this order, and the order is the point:

1. The request is written to ``support_requests``. It is saved before anything is sent,
   so a mail server that is down costs a notification rather than the question.
2. The letter is addressed. ``Settings → Email`` may name a support address; when it does
   not, the administrators' confirmed addresses are used, because a question with nowhere
   to go is worse than one that lands in several inboxes.
3. The letter is handed to the mailer, and where it ended up is recorded on the row --
   ``sent``, ``outbox`` (no SMTP configured yet) or ``failed`` (with the reason).

The copy lives here rather than in ``mail.py`` for the same reason the signup letters
live in ``accounts.py``: it is product text in two languages, not transport.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from slipwright.accounts import Letter
from slipwright.auth import InvalidEmail, normalise_email
from slipwright.mail import Mailer, MailError, MailSettings, OutboxMailer
from slipwright.store import JobStore

log = logging.getLogger(__name__)

#: Requests one account may open in an hour. Support is a form anybody signed in can
#: post to, so it is rationed like the other unauthenticated-ish doors.
SUPPORT_LIMIT = 10
WINDOW_S = 3600

#: What the page offers. The value is stored; the label is translated in the browser.
CATEGORIES = ("question", "problem", "billing", "feature", "other")


class SupportError(RuntimeError):
    """The request could not be accepted. Carries text fit to show the sender."""


class TooManyRequests(SupportError):
    pass


def _category(value: str) -> str:
    return value if value in CATEGORIES else "other"


def support_letter(
    lang: str,
    *,
    name: str,
    email: str,
    category: str,
    subject: str,
    message: str,
    request_id: str,
) -> Letter:
    """The letter the support address receives. Written to be answered by pressing reply,
    so the sender's address is on its own line near the top."""
    who = name or email
    if lang == "tr":
        return Letter(
            subject=f"[Slipwright destek] {subject}",
            body=(
                f"{who} destek talebi gönderdi.\n\n"
                f"Gönderen : {who} <{email}>\n"
                f"Konu başlığı: {subject}\n"
                f"Kategori : {category}\n"
                f"Talep no : {request_id}\n\n"
                "--------------------------------------------------\n"
                f"{message}\n"
                "--------------------------------------------------\n\n"
                f"Yanıtlamak için doğrudan {email} adresine cevap yazabilirsin.\n"
            ),
        )
    return Letter(
        subject=f"[Slipwright support] {subject}",
        body=(
            f"{who} sent a support request.\n\n"
            f"From    : {who} <{email}>\n"
            f"Subject : {subject}\n"
            f"Category: {category}\n"
            f"Request : {request_id}\n\n"
            "--------------------------------------------------\n"
            f"{message}\n"
            "--------------------------------------------------\n\n"
            f"Reply straight to {email} to answer it.\n"
        ),
    )


def receipt_letter(lang: str, *, name: str, subject: str, request_id: str) -> Letter:
    """The short acknowledgement the sender gets, so they know it arrived somewhere."""
    who = name or ""
    if lang == "tr":
        return Letter(
            subject=f"Slipwright: talebini aldık — {subject}",
            body=(
                f"Merhaba {who},\n\n"
                "Destek talebini aldık; en kısa sürede döneceğiz.\n\n"
                f"Talep no: {request_id}\n"
                f"Konu    : {subject}\n\n"
                "Bu postaya cevap yazman gerekmiyor.\n"
            ),
        )
    return Letter(
        subject=f"Slipwright: we have your request — {subject}",
        body=(
            f"Hello {who},\n\n"
            "We have your support request and will come back to you shortly.\n\n"
            f"Request: {request_id}\n"
            f"Subject: {subject}\n\n"
            "No reply is needed to this message.\n"
        ),
    )


def test_letter(lang: str, *, host: str) -> Letter:
    """What ``Send a test message`` puts in the inbox: enough to prove the settings work."""
    if lang == "tr":
        return Letter(
            subject="Slipwright: e-posta ayarları çalışıyor",
            body=(
                "Bu bir deneme postası.\n\n"
                f"Slipwright bu mesajı {host} üzerinden gönderdi. Onu okuyabiliyorsan "
                "e-posta ayarların doğru: doğrulama, şifre sıfırlama ve destek postaları "
                "buradan çıkacak.\n"
            ),
        )
    return Letter(
        subject="Slipwright: your email settings work",
        body=(
            "This is a test message.\n\n"
            f"Slipwright sent it through {host}. If you are reading it, your email "
            "settings are right: verification links, password resets and support "
            "requests will go out the same way.\n"
        ),
    )


@dataclass
class SupportDesk:
    """Takes a request, saves it, and posts it on. One per engine call; holds no state."""

    store: JobStore
    mailer: Mailer
    settings: MailSettings

    # -- who gets it -----------------------------------------------------------------

    def recipients(self) -> list[str]:
        """The support address if one is set, otherwise every administrator who has
        confirmed an address. Empty only on an installation with neither."""
        configured = (self.settings.support_email or "").strip()
        if configured:
            parts = configured.replace(";", ",").split(",")
            return [a for a in (_clean(part) for part in parts) if a]
        return [
            u.email
            for u in self.store.list_users()
            if u.is_admin and u.email and u.email_verified_at is not None
        ]

    # -- taking one ------------------------------------------------------------------

    def submit(
        self,
        *,
        email: str,
        subject: str,
        message: str,
        user_id: str | None = None,
        name: str = "",
        category: str = "other",
        lang: str = "tr",
    ) -> dict[str, Any]:
        """Save the request and send it on. Never raises for a mail failure: the row is
        already safe, and the page says which of the three things happened."""
        try:
            address = normalise_email(email)
        except InvalidEmail as exc:
            raise SupportError(str(exc)) from exc
        bucket = f"support:{user_id or address}"
        if self.store.hit_rate_limit(bucket, limit=SUPPORT_LIMIT, window_s=WINDOW_S):
            raise TooManyRequests("too many support requests; try again later")

        row = self.store.create_support_request(
            email=address,
            subject=subject,
            message=message,
            user_id=user_id,
            name=name,
            category=_category(category),
        )
        to = self.recipients()
        if not to:
            log.warning(
                "support request %s has nowhere to go: no support address, no admins", row["id"]
            )
            return self.store.record_support_delivery(
                row["id"],
                delivery="failed",
                error=(
                    "no support address is configured and no administrator has a "
                    "confirmed address"
                ),
            )

        letter = support_letter(
            lang,
            name=row["name"],
            email=address,
            category=row["category"],
            subject=row["subject"],
            message=row["message"],
            request_id=row["id"],
        )
        # The outbox is a real destination, not a failure: an installation without SMTP
        # still keeps the question where an admin can read it.
        parked = isinstance(self.mailer, OutboxMailer)
        try:
            for one in to:
                self.mailer.send(one, letter.subject, letter.body)
        except MailError as exc:
            log.warning("support request %s could not be sent: %s", row["id"], exc)
            return self.store.record_support_delivery(
                row["id"], delivery="failed", sent_to=", ".join(to), error=str(exc)
            )

        if not parked:
            # Best effort, and deliberately after the real one: a receipt that fails must
            # not make a delivered request look undelivered.
            receipt = receipt_letter(
                lang, name=row["name"], subject=row["subject"], request_id=row["id"]
            )
            try:
                self.mailer.send(address, receipt.subject, receipt.body)
            except MailError as exc:
                log.info("support receipt for %s not sent: %s", address, exc)

        return self.store.record_support_delivery(
            row["id"], delivery="outbox" if parked else "sent", sent_to=", ".join(to)
        )

    # -- proving the settings --------------------------------------------------------

    def send_test(self, to: str, *, lang: str = "tr") -> str:
        """Send a test message. Raises ``SupportError`` with text fit for the page."""
        try:
            address = normalise_email(to)
        except InvalidEmail as exc:
            raise SupportError(str(exc)) from exc
        letter = test_letter(lang, host=self.settings.host or "the outbox")
        try:
            self.mailer.send(address, letter.subject, letter.body)
        except MailError as exc:
            raise SupportError(str(exc)) from exc
        return address


def _clean(value: str) -> str:
    try:
        return normalise_email(value)
    except InvalidEmail:
        return ""


__all__ = [
    "CATEGORIES",
    "SUPPORT_LIMIT",
    "SupportDesk",
    "SupportError",
    "TooManyRequests",
    "receipt_letter",
    "support_letter",
    "test_letter",
]
