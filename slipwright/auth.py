"""Users, sessions and API tokens.

Single-tenant and local: users live in the store, passwords are hashed with scrypt
(stdlib, memory-hard, no native dependency), browser sessions are random tokens in an
HttpOnly cookie and CLI access uses bearer tokens. Only hashes of session and bearer
tokens are stored, so a copy of the database cannot be used to log in.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.job import new_job_id, utcnow

SESSION_COOKIE = "slipwright_session"
SESSION_TTL = timedelta(days=14)
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
_HASH_VERSION = "scrypt1"


class User(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id)
    username: str = Field(min_length=1, max_length=64)
    is_admin: bool = False
    created_at: datetime = Field(default_factory=utcnow)


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
    "SESSION_COOKIE",
    "SESSION_TTL",
    "ApiToken",
    "TokenKind",
    "User",
    "hash_password",
    "new_secret",
    "token_hash",
    "verify_password",
]
