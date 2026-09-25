"""Signing up, proving an address and getting back in after forgetting a password.

The three flows that turn a private installation into one strangers can join. All of them
are rate-limited, none of them tell a caller whether an address exists, and each writes
exactly one letter through ``slipwright/mail.py``.

The letters are written here rather than in the mail module because they are product
copy, not transport: they carry the platform's two languages and the link back into the
application.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from slipwright.auth import (
    EmailTokenKind,
    User,
    check_password,
    normalise_email,
)
from slipwright.demo import seed_demo_project
from slipwright.mail import Mailer, MailError, MailSettings
from slipwright.store import JobStore
from slipwright.store.users import EmailTaken

log = logging.getLogger(__name__)

#: Signups from one address, and password resets for one account, in an hour.
SIGNUP_LIMIT = 5
RESET_LIMIT = 5
#: Failed logins before an address is made to wait.
LOGIN_LIMIT = 10
WINDOW_S = 3600


@dataclass(frozen=True)
class Letter:
    subject: str
    body: str


def _link(base_url: str, path: str, secret: str) -> str:
    root = (base_url or "").rstrip("/")
    return f"{root}{path}?token={secret}"


def verify_letter(lang: str, *, link: str, name: str) -> Letter:
    if lang == "tr":
        return Letter(
            subject="Slipwright: e-posta adresini doğrula",
            body=(
                f"Merhaba {name},\n\n"
                "Slipwright hesabını açmak için adresini doğrulaman gerekiyor. "
                "Aşağıdaki bağlantıya tıkla:\n\n"
                f"{link}\n\n"
                "Bağlantı 24 saat geçerli. Bu hesabı sen açmadıysan bu postayı yok sayabilirsin.\n"
            ),
        )
    return Letter(
        subject="Slipwright: confirm your email address",
        body=(
            f"Hello {name},\n\n"
            "Confirm your address to finish setting up your Slipwright account:\n\n"
            f"{link}\n\n"
            "The link is good for 24 hours. If you did not create this account, ignore "
            "this message.\n"
        ),
    )


def reset_letter(lang: str, *, link: str, name: str) -> Letter:
    if lang == "tr":
        return Letter(
            subject="Slipwright: şifre sıfırlama",
            body=(
                f"Merhaba {name},\n\n"
                "Şifreni sıfırlamak için aşağıdaki bağlantıya tıkla:\n\n"
                f"{link}\n\n"
                "Bağlantı 2 saat geçerli ve bir kez kullanılabilir. Bu isteği sen "
                "yapmadıysan hiçbir şey yapmana gerek yok; şifren değişmedi.\n"
            ),
        )
    return Letter(
        subject="Slipwright: reset your password",
        body=(
            f"Hello {name},\n\n"
            "Use this link to set a new password:\n\n"
            f"{link}\n\n"
            "It is good for two hours and works once. If you did not ask for this, you "
            "need do nothing: your password has not changed.\n"
        ),
    )


class Accounts:
    """The signup, verification and reset flows over a store and a mailer."""

    def __init__(
        self,
        store: JobStore,
        mailer: Mailer,
        settings: MailSettings,
        *,
        demo_project: bool = True,
    ) -> None:
        self.store = store
        self.mailer = mailer
        self.settings = settings
        # an installation that would rather people started from nothing turns it off
        self.demo_project = demo_project

    # -- signup --------------------------------------------------------------------------

    def sign_up(self, email: str, password: str, name: str, *, lang: str = "tr") -> User:
        """Create an unverified account and mail the link that proves the address.

        Raises ``EmailTaken`` when the address is already in use and ``WeakPassword`` when
        the password is too short; the caller turns those into 409 and 422.
        """
        address = normalise_email(email)
        check_password(password)
        if self.store.hit_rate_limit(
            f"signup:{address}", limit=SIGNUP_LIMIT, window_s=WINDOW_S
        ):
            raise TooManyAttempts("signup")
        user = self.store.create_user(
            (name or address.split("@")[0]).strip(), password, email=address, is_admin=False
        )
        self.send_verification(user, lang=lang)
        return user

    def send_verification(self, user: User, *, lang: str = "tr") -> None:
        """Issue a fresh link and mail it. Any earlier one stops working."""
        if user.email is None or user.email_verified_at is not None:
            return
        secret = self.store.issue_email_token(user.id, EmailTokenKind.VERIFY, user.email)
        letter = verify_letter(
            lang,
            link=_link(self.settings.base_url, "/verify", secret),
            name=user.username,
        )
        self._deliver(user.email, letter)

    def verify(self, secret: str) -> User | None:
        """Redeem a verification link. ``None`` when it is no longer good.

        This is where the worked example is put in place -- at the moment somebody
        becomes a real account, rather than when they merely claimed an address. They
        have no model key yet, so it is the only thing there is to look at.
        """
        user = self.store.spend_email_token(secret, EmailTokenKind.VERIFY)
        if user is None:
            return None
        verified = self.store.mark_email_verified(user.id)
        if self.demo_project:
            seed_demo_project(self.store, verified.id)
        return verified

    # -- password reset ------------------------------------------------------------------

    def request_reset(self, email: str, *, lang: str = "tr") -> None:
        """Mail a reset link if the address belongs to an account.

        Deliberately silent either way: the caller answers 204 whatever happened, so this
        endpoint cannot be used to find out who has an account here.
        """
        try:
            address = normalise_email(email)
        except ValueError:
            return
        if self.store.hit_rate_limit(f"reset:{address}", limit=RESET_LIMIT, window_s=WINDOW_S):
            return
        user = self.store.find_by_email(address)
        if user is None or not user.active:
            return
        secret = self.store.issue_email_token(user.id, EmailTokenKind.RESET, address)
        letter = reset_letter(
            lang, link=_link(self.settings.base_url, "/reset", secret), name=user.username
        )
        self._deliver(address, letter)

    def reset_password(self, secret: str, password: str) -> User | None:
        """Set a new password from a reset link and drop every session and token."""
        check_password(password)
        user = self.store.spend_email_token(secret, EmailTokenKind.RESET)
        if user is None:
            return None
        self.store.set_password(user.id, password)
        # somebody who proves the address owns the account, whatever it said before
        if user.email_verified_at is None:
            self.store.mark_email_verified(user.id)
        return self.store.get_user(user.id)

    # -- helpers -------------------------------------------------------------------------

    def _deliver(self, to: str, letter: Letter) -> None:
        try:
            self.mailer.send(to, letter.subject, letter.body)
        except MailError as exc:
            # the account already exists; losing the letter must not lose the signup
            log.warning("could not deliver to %s: %s", to, exc)


class TooManyAttempts(RuntimeError):
    def __init__(self, what: str) -> None:
        super().__init__(f"too many {what} attempts; try again later")
        self.what = what


__all__ = [
    "LOGIN_LIMIT",
    "RESET_LIMIT",
    "SIGNUP_LIMIT",
    "WINDOW_S",
    "Accounts",
    "EmailTaken",
    "Letter",
    "TooManyAttempts",
    "reset_letter",
    "verify_letter",
]
