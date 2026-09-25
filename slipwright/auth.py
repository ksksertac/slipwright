"""Users, sessions and API tokens.

People are identified by an **email address**: it is what they sign up with, what they log
in with, and the only way back into an account whose password is lost. ``username`` stayed
behind as the display name, because a person is nicer to read than an address.

Passwords are hashed with scrypt (stdlib, memory-hard, no native dependency), browser
sessions are random tokens in an HttpOnly cookie and CLI access uses bearer tokens. Only
hashes of session, bearer and email tokens are stored, so a copy of the database cannot be
used to log in or to claim somebody's address.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from slipwright.schemas.job import new_job_id, utcnow

SESSION_COOKIE = "slipwright_session"
SESSION_TTL = timedelta(days=14)
#: How long a verification or password-reset link stays good.
EMAIL_TOKEN_TTL = timedelta(hours=24)
#: A reset link is shorter-lived than a verification one: it opens an existing account.
RESET_TOKEN_TTL = timedelta(hours=2)
#: An invitation waits for somebody who may not read their mail today.
INVITE_TOKEN_TTL = timedelta(days=7)
MIN_PASSWORD = 8
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
_HASH_VERSION = "scrypt1"

# Deliberately permissive. The address is proved by sending mail to it, not by a regular
# expression, and every clever pattern rejects somebody's real address.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


class InvalidEmail(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(f"not an email address: {value}")
        self.value = value


def normalise_email(value: str) -> str:
    """Lowercased and trimmed, so one person cannot hold two spellings of one address."""
    email = value.strip().lower()
    if not _EMAIL.match(email):
        raise InvalidEmail(value)
    return email


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"  # an admin closed the account; nothing is deleted
    #: invited to an agent and not yet answered: the row exists (so the address is taken
    #: and the invitation has somewhere to point) but there is no password to log in with
    INVITED = "invited"
    #: was on a team and is on none any more. The row stays: the address belongs to the
    #: organisation that invited it, and the history of what the person approved stays
    #: readable. Logging in says so rather than failing as a wrong password.
    REMOVED = "removed"


class User(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id)
    username: str = Field(min_length=1, max_length=64, description="Display name.")
    email: str | None = Field(
        default=None,
        description="Login identity. Absent only on accounts made before signup existed.",
    )
    email_verified_at: datetime | None = Field(
        default=None, description="When the address was proved; until then, work is refused."
    )
    owner_id: str | None = Field(
        default=None,
        description="The account this person belongs to: set on somebody an administrator "
        "invited onto an agent, null on an account that is its own. It is what makes a "
        "member see the administrator's projects rather than an empty installation.",
    )
    status: UserStatus = UserStatus.ACTIVE
    is_admin: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("email")
    @classmethod
    def _lowercase(cls, value: str | None) -> str | None:
        return None if value is None else value.strip().lower()

    @property
    def verified(self) -> bool:
        """An account with no address at all is a pre-signup one: it is trusted."""
        return self.email is None or self.email_verified_at is not None

    @property
    def active(self) -> bool:
        return self.status is UserStatus.ACTIVE

    @property
    def is_member(self) -> bool:
        """On somebody else's team: what they may do comes from their agents, not from
        owning anything."""
        return self.owner_id is not None

    @property
    def tenant_id(self) -> str:
        """Whose data this person works on -- their own account, or the one that invited
        them. Every ownership check reads this and not ``id``."""
        return self.owner_id or self.id


class EmailTokenKind(StrEnum):
    VERIFY = "verify"
    RESET = "reset"
    INVITE = "invite"  # come and be the Architect on this team


class TokenKind(StrEnum):
    SESSION = "session"
    BEARER = "bearer"


class ApiToken(BaseModel):
    """A bearer token's public half; the secret is shown once at creation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id)
    user_id: str
    name: str = "cli"
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


# -- passwords ---------------------------------------------------------------------------


class WeakPassword(ValueError):
    def __init__(self) -> None:
        super().__init__(f"password must be at least {MIN_PASSWORD} characters")


def check_password(password: str) -> str:
    """The one rule: long enough. Length beats character classes, and a rule nobody can
    satisfy is a rule everybody writes on a sticky note."""
    if len(password) < MIN_PASSWORD:
        raise WeakPassword
    return password


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"{_HASH_VERSION}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        version, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if version != _HASH_VERSION:
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


# -- tokens ------------------------------------------------------------------------------


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def token_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


__all__ = [
    "EMAIL_TOKEN_TTL",
    "INVITE_TOKEN_TTL",
    "MIN_PASSWORD",
    "RESET_TOKEN_TTL",
    "SESSION_COOKIE",
    "SESSION_TTL",
    "ApiToken",
    "EmailTokenKind",
    "InvalidEmail",
    "TokenKind",
    "User",
    "UserStatus",
    "WeakPassword",
    "check_password",
    "hash_password",
    "new_secret",
    "normalise_email",
    "token_hash",
    "verify_password",
]
