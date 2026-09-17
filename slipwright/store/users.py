"""User, session and bearer-token tables, mixed into ``JobStore``."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime

from slipwright.auth import (
    SESSION_TTL,
    ApiToken,
    User,
    hash_password,
    new_secret,
    token_hash,
    verify_password,
)
from slipwright.schemas.job import utcnow

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash    TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT,
    revoked_at    TEXT
);
"""


class UserNotFound(KeyError):
    def __init__(self, ref: str) -> None:
        super().__init__(ref)
        self.ref = ref

    def __str__(self) -> str:
        return f"user not found: {self.ref}"


class UsernameTaken(ValueError):
    def __init__(self, username: str) -> None:
        super().__init__(f"username already taken: {username}")
        self.username = username


class UserStoreMixin:
    """Requires the host class to provide ``_conn``, ``_lock`` and ``_tx``."""

    _conn: sqlite3.Connection
    _lock: threading.RLock
    _tx: Callable[[], AbstractContextManager[sqlite3.Connection]]

    # -- users -------------------------------------------------------------------------

    def create_user(self, username: str, password: str, *, is_admin: bool | None = None) -> User:
        """Create a user. The very first user is an admin unless told otherwise."""
        username = username.strip()
        if not username:
            raise ValueError("username must not be empty")
        password_hash = hash_password(password)
        with self._tx() as conn:
            if is_admin is None:
                is_admin = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
            user = User(username=username, is_admin=is_admin)
            try:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, is_admin, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        user.id,
                        user.username,
                        password_hash,
                        int(user.is_admin),
                        user.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise UsernameTaken(username) from exc
        return user

    def get_user(self, user_id: str) -> User:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise UserNotFound(user_id)
        return self._row_to_user(row)

    def find_user(self, username: str) -> User | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
        return None if row is None else self._row_to_user(row)

    def list_users(self) -> list[User]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM users ORDER BY created_at, id").fetchall()
        return [self._row_to_user(r) for r in rows]

    def count_users(self) -> int:
        with self._lock:
            n: int = self._conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        return n

    def authenticate(self, username: str, password: str) -> User | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return self._row_to_user(row)

    def set_password(self, user_id: str, password: str) -> None:
        """Change a password; every session and token of the user is invalidated."""
        password_hash = hash_password(password)
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
            )
            if cur.rowcount == 0:
                raise UserNotFound(user_id)
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute(
                "UPDATE api_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (utcnow().isoformat(), user_id),
            )

    def set_admin(self, user_id: str, is_admin: bool) -> User:
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id)
            )
            if cur.rowcount == 0:
                raise UserNotFound(user_id)
        return self.get_user(user_id)

    def delete_user(self, user_id: str) -> None:
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            if cur.rowcount == 0:
                raise UserNotFound(user_id)

    # -- sessions ----------------------------------------------------------------------

    def create_session(self, user_id: str) -> str:
        """Start a session and return its secret (the cookie value)."""
        secret = new_secret()
        now = utcnow()
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token_hash(secret), user_id, now.isoformat(), (now + SESSION_TTL).isoformat()),
            )
        return secret

    def session_user(self, secret: str) -> User | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ?",
                (token_hash(secret),),
            ).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) < utcnow():
            return None
        return self._row_to_user(row)

    def delete_session(self, secret: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(secret),))

    # -- bearer tokens -----------------------------------------------------------------

    def create_token(self, user_id: str, name: str = "cli") -> tuple[ApiToken, str]:
        """Issue a bearer token; the secret is returned once and never stored."""
        self.get_user(user_id)
        secret = new_secret()
        token = ApiToken(user_id=user_id, name=name)
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO api_tokens (id, user_id, name, token_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (token.id, user_id, name, token_hash(secret), token.created_at.isoformat()),
            )
        return token, secret

    def token_user(self, secret: str) -> User | None:
        h = token_hash(secret)
        with self._tx() as conn:
            row = conn.execute(
                "SELECT u.* FROM api_tokens t JOIN users u ON u.id = t.user_id "
                "WHERE t.token_hash = ? AND t.revoked_at IS NULL",
                (h,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?",
                (utcnow().isoformat(), h),
            )
        return self._row_to_user(row)

    def list_tokens(self, user_id: str) -> list[ApiToken]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM api_tokens WHERE user_id = ? ORDER BY created_at, id", (user_id,)
            ).fetchall()
        return [self._row_to_token(r) for r in rows]

    def get_token(self, token_id: str) -> ApiToken:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM api_tokens WHERE id = ?", (token_id,)
            ).fetchone()
        if row is None:
            raise UserNotFound(f"token {token_id}")
        return self._row_to_token(row)

    def revoke_token(self, token_id: str) -> ApiToken:
        with self._tx() as conn:
            conn.execute(
                "UPDATE api_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (utcnow().isoformat(), token_id),
            )
            row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
        if row is None:
            raise UserNotFound(f"token {token_id}")
        return self._row_to_token(row)

    # -- helpers -----------------------------------------------------------------------

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_token(row: sqlite3.Row) -> ApiToken:
        return ApiToken(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_used_at=(
                None if row["last_used_at"] is None else datetime.fromisoformat(row["last_used_at"])
            ),
            revoked_at=(
                None if row["revoked_at"] is None else datetime.fromisoformat(row["revoked_at"])
            ),
        )


__all__ = ["USERS_SCHEMA", "UserNotFound", "UserStoreMixin", "UsernameTaken"]
