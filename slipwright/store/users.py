"""User, session and bearer-token tables, mixed into ``JobStore``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from slipwright.auth import (
    EMAIL_TOKEN_TTL,
    INVITE_TOKEN_TTL,
    RESET_TOKEN_TTL,
    SESSION_TTL,
    ApiToken,
    EmailTokenKind,
    User,
    UserStatus,
    hash_password,
    new_secret,
    normalise_email,
    token_hash,
    verify_password,
)
from slipwright.schemas.job import utcnow
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import api_tokens, email_tokens, rate_limits, sessions, users


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


class EmailTaken(ValueError):
    def __init__(self, email: str) -> None:
        super().__init__(f"there is already an account for {email}")
        self.email = email


class UserStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    # -- users -------------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password: str,
        *,
        is_admin: bool | None = None,
        email: str | None = None,
        verified: bool = False,
        owner_id: str | None = None,
        status: UserStatus = UserStatus.ACTIVE,
    ) -> User:
        """Create a user. The very first user is an admin unless told otherwise.

        ``email`` is what a signup supplies; an account made by an administrator may still
        have none, and logs in by username as it always did. ``owner_id`` and ``status``
        are what an invitation sets: an account that belongs to a team and cannot be
        logged into until it is accepted (``slipwright/teams.py``).
        """
        username = username.strip()
        if not username:
            raise ValueError("username must not be empty")
        address = None if email is None else normalise_email(email)
        password_hash = hash_password(password)
        if address is not None and self.find_by_email(address) is not None:
            raise EmailTaken(address)
        with self.db.begin() as conn:
            if is_admin is None:
                total = conn.execute(select(func.count()).select_from(users)).scalar_one()
                is_admin = total == 0
            user = User(
                username=username,
                email=address,
                is_admin=is_admin,
                owner_id=owner_id,
                status=status,
                email_verified_at=utcnow() if (verified and address) else None,
            )
            try:
                conn.execute(
                    insert(users).values(
                        id=user.id,
                        username=user.username,
                        email=user.email,
                        email_verified_at=(
                            None
                            if user.email_verified_at is None
                            else user.email_verified_at.isoformat()
                        ),
                        status=user.status.value,
                        owner_id=user.owner_id,
                        password_hash=password_hash,
                        is_admin=int(user.is_admin),
                        created_at=user.created_at.isoformat(),
                    )
                )
            except IntegrityError as exc:
                if address is not None and "email" in str(exc).lower():
                    raise EmailTaken(address) from exc
                raise UsernameTaken(username) from exc
        return user

    def find_by_email(self, email: str) -> User | None:
        with self.db.connect() as conn:
            row = one(conn.execute(select(users).where(users.c.email == email.strip().lower())))
        return None if row is None else self._row_to_user(row)

    def get_user(self, user_id: str) -> User:
        with self.db.connect() as conn:
            row = one(conn.execute(select(users).where(users.c.id == user_id)))
        if row is None:
            raise UserNotFound(user_id)
        return self._row_to_user(row)

    def find_user(self, username: str) -> User | None:
        with self.db.connect() as conn:
            row = one(conn.execute(select(users).where(users.c.username == username.strip())))
        return None if row is None else self._row_to_user(row)

    def list_users(self, owner_id: str | None = None) -> list[User]:
        """Every account, or -- with ``owner_id`` -- one owner and the people on its team."""
        query = select(users)
        if owner_id is not None:
            query = query.where((users.c.id == owner_id) | (users.c.owner_id == owner_id))
        with self.db.connect() as conn:
            found = rows(conn.execute(query.order_by(users.c.created_at, users.c.id)))
        return [self._row_to_user(r) for r in found]

    def rename_user(self, user_id: str, username: str) -> User:
        """Change the display name. Somebody invited by address names themselves when
        they accept."""
        name = username.strip()
        if not name:
            raise ValueError("username must not be empty")
        with self.db.begin() as conn:
            try:
                changed = conn.execute(
                    update(users).where(users.c.id == user_id).values(username=name)
                )
            except IntegrityError as exc:
                raise UsernameTaken(name) from exc
            if changed.rowcount == 0:
                raise UserNotFound(user_id)
        return self.get_user(user_id)

    def count_users(self) -> int:
        with self.db.connect() as conn:
            total: int = conn.execute(select(func.count()).select_from(users)).scalar_one()
        return total

    def authenticate(
        self, identifier: str, password: str, *, allow_inactive: bool = False
    ) -> User | None:
        """Log in by email address or, for an account that predates signup, by username.

        A suspended account fails here rather than later, and the password is verified
        either way so a wrong identifier and a wrong password take the same time.

        ``allow_inactive`` hands back an account that proved its password but may not come
        in -- suspended, or taken off the last of its agents -- so the login page can say
        which of the two it is instead of "wrong password". Nothing is revealed that the
        password did not already open.
        """
        value = identifier.strip()
        query = select(users).where(
            (users.c.email == value.lower()) | (users.c.username == value)
        )
        with self.db.connect() as conn:
            row = one(conn.execute(query))
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        user = self._row_to_user(row)
        return user if (allow_inactive or user.active) else None

    def set_password(self, user_id: str, password: str) -> None:
        """Change a password; every session and token of the user is invalidated."""
        password_hash = hash_password(password)
        with self.db.begin() as conn:
            changed = conn.execute(
                update(users).where(users.c.id == user_id).values(password_hash=password_hash)
            )
            if changed.rowcount == 0:
                raise UserNotFound(user_id)
            conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
            conn.execute(
                update(api_tokens)
                .where(api_tokens.c.user_id == user_id, api_tokens.c.revoked_at.is_(None))
                .values(revoked_at=utcnow().isoformat())
            )

    def set_admin(self, user_id: str, is_admin: bool) -> User:
        with self.db.begin() as conn:
            changed = conn.execute(
                update(users).where(users.c.id == user_id).values(is_admin=int(is_admin))
            )
            if changed.rowcount == 0:
                raise UserNotFound(user_id)
        return self.get_user(user_id)

    def delete_user(self, user_id: str) -> None:
        with self.db.begin() as conn:
            changed = conn.execute(delete(users).where(users.c.id == user_id))
            if changed.rowcount == 0:
                raise UserNotFound(user_id)

    def set_status(self, user_id: str, status: UserStatus) -> User:
        """Suspend, remove or restore an account.

        Suspending drops the sessions, so the person is out of the application at once
        rather than at the next login. Being taken off the last agent does not: the
        session is refused at the door either way, and keeping it is what lets the door
        say *you were taken off the team* instead of the browser quietly forgetting who
        it was.
        """
        with self.db.begin() as conn:
            changed = conn.execute(
                update(users).where(users.c.id == user_id).values(status=status.value)
            )
            if changed.rowcount == 0:
                raise UserNotFound(user_id)
            if status is UserStatus.SUSPENDED:
                conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
        return self.get_user(user_id)

    # -- email verification and password reset -----------------------------------------

    def issue_email_token(self, user_id: str, kind: EmailTokenKind, email: str) -> str:
        """A one-shot secret to mail out. Only its hash is kept.

        Issuing a new token of a kind spends the outstanding ones of that kind, so the
        last link sent is the only one that works -- which is what a person who clicked
        "send it again" expects.
        """
        secret = new_secret()
        now = utcnow()
        ttl = {
            EmailTokenKind.VERIFY: EMAIL_TOKEN_TTL,
            EmailTokenKind.RESET: RESET_TOKEN_TTL,
            EmailTokenKind.INVITE: INVITE_TOKEN_TTL,
        }[kind]
        with self.db.begin() as conn:
            conn.execute(
                update(email_tokens)
                .where(
                    email_tokens.c.user_id == user_id,
                    email_tokens.c.kind == kind.value,
                    email_tokens.c.used_at.is_(None),
                )
                .values(used_at=now.isoformat())
            )
            conn.execute(
                insert(email_tokens).values(
                    token_hash=token_hash(secret),
                    user_id=user_id,
                    kind=kind.value,
                    email=email.strip().lower(),
                    created_at=now.isoformat(),
                    expires_at=(now + ttl).isoformat(),
                )
            )
        return secret

    def peek_email_token(self, secret: str, kind: EmailTokenKind) -> User | None:
        """Who a link is for, without spending it.

        An invitation is read before it is answered -- the page names the agent and who
        sent it -- and opening that page must not use the link up.
        """
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(email_tokens).where(
                        email_tokens.c.token_hash == token_hash(secret),
                        email_tokens.c.kind == kind.value,
                        email_tokens.c.used_at.is_(None),
                    )
                )
            )
        if row is None or datetime.fromisoformat(row["expires_at"]) < utcnow():
            return None
        return self.get_user(row["user_id"])

    def spend_email_token(self, secret: str, kind: EmailTokenKind) -> User | None:
        """Redeem a link. ``None`` when it is unknown, of the wrong kind, already used or
        expired -- the caller says only "this link is no longer good", never which."""
        digest = token_hash(secret)
        now = utcnow()
        with self.db.begin() as conn:
            row = one(
                conn.execute(
                    select(email_tokens).where(
                        email_tokens.c.token_hash == digest,
                        email_tokens.c.kind == kind.value,
                        email_tokens.c.used_at.is_(None),
                    )
                )
            )
            if row is None or datetime.fromisoformat(row["expires_at"]) < now:
                return None
            conn.execute(
                update(email_tokens)
                .where(email_tokens.c.token_hash == digest)
                .values(used_at=now.isoformat())
            )
        return self.get_user(row["user_id"])

    def mark_email_verified(self, user_id: str) -> User:
        with self.db.begin() as conn:
            changed = conn.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(email_verified_at=utcnow().isoformat())
            )
            if changed.rowcount == 0:
                raise UserNotFound(user_id)
        return self.get_user(user_id)

    # -- rate limiting -------------------------------------------------------------------

    def hit_rate_limit(self, bucket: str, *, limit: int, window_s: int) -> bool:
        """Count one attempt. ``True`` means this one is over the line and must be refused.

        A fixed window, not a sliding one: it is a handful of rows, it needs no background
        sweep, and the failure mode (a burst straddling two windows) does not matter for
        signups and password resets.
        """
        now = utcnow()
        with self.db.begin() as conn:
            row = one(
                conn.execute(select(rate_limits).where(rate_limits.c.bucket == bucket))
            )
            if (
                row is None
                or (now - datetime.fromisoformat(row["window_start"])).total_seconds() >= window_s
            ):
                conn.execute(
                    self.db.upsert(
                        rate_limits,
                        {"bucket": bucket, "window_start": now.isoformat(), "count": 1},
                        key=["bucket"],
                        update=["window_start", "count"],
                    )
                )
                return False
            count = int(row["count"]) + 1
            conn.execute(
                update(rate_limits).where(rate_limits.c.bucket == bucket).values(count=count)
            )
            return count > limit

    # -- sessions ----------------------------------------------------------------------

    def create_session(self, user_id: str) -> str:
        """Start a session and return its secret (the cookie value)."""
        secret = new_secret()
        now = utcnow()
        with self.db.begin() as conn:
            conn.execute(
                insert(sessions).values(
                    token_hash=token_hash(secret),
                    user_id=user_id,
                    created_at=now.isoformat(),
                    expires_at=(now + SESSION_TTL).isoformat(),
                )
            )
        return secret

    def session_user(self, secret: str) -> User | None:
        query = (
            select(users, sessions.c.expires_at)
            .select_from(sessions.join(users, users.c.id == sessions.c.user_id))
            .where(sessions.c.token_hash == token_hash(secret))
        )
        with self.db.connect() as conn:
            row = one(conn.execute(query))
        if row is None or datetime.fromisoformat(row["expires_at"]) < utcnow():
            return None
        return self._row_to_user(row)

    def delete_session(self, secret: str) -> None:
        with self.db.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.token_hash == token_hash(secret)))

    # -- bearer tokens -----------------------------------------------------------------

    def create_token(self, user_id: str, name: str = "cli") -> tuple[ApiToken, str]:
        """Issue a bearer token; the secret is returned once and never stored."""
        self.get_user(user_id)
        secret = new_secret()
        token = ApiToken(user_id=user_id, name=name)
        with self.db.begin() as conn:
            conn.execute(
                insert(api_tokens).values(
                    id=token.id,
                    user_id=user_id,
                    name=name,
                    token_hash=token_hash(secret),
                    created_at=token.created_at.isoformat(),
                )
            )
        return token, secret

    def token_user(self, secret: str) -> User | None:
        digest = token_hash(secret)
        query = (
            select(users)
            .select_from(api_tokens.join(users, users.c.id == api_tokens.c.user_id))
            .where(api_tokens.c.token_hash == digest, api_tokens.c.revoked_at.is_(None))
        )
        with self.db.begin() as conn:
            row = one(conn.execute(query))
            if row is None:
                return None
            conn.execute(
                update(api_tokens)
                .where(api_tokens.c.token_hash == digest)
                .values(last_used_at=utcnow().isoformat())
            )
        return self._row_to_user(row)

    def list_tokens(self, user_id: str) -> list[ApiToken]:
        query = (
            select(api_tokens)
            .where(api_tokens.c.user_id == user_id)
            .order_by(api_tokens.c.created_at, api_tokens.c.id)
        )
        with self.db.connect() as conn:
            found = rows(conn.execute(query))
        return [self._row_to_token(r) for r in found]

    def get_token(self, token_id: str) -> ApiToken:
        with self.db.connect() as conn:
            row = one(conn.execute(select(api_tokens).where(api_tokens.c.id == token_id)))
        if row is None:
            raise UserNotFound(f"token {token_id}")
        return self._row_to_token(row)

    def revoke_token(self, token_id: str) -> ApiToken:
        with self.db.begin() as conn:
            conn.execute(
                update(api_tokens)
                .where(api_tokens.c.id == token_id, api_tokens.c.revoked_at.is_(None))
                .values(revoked_at=utcnow().isoformat())
            )
            row = one(conn.execute(select(api_tokens).where(api_tokens.c.id == token_id)))
        if row is None:
            raise UserNotFound(f"token {token_id}")
        return self._row_to_token(row)

    # -- helpers -----------------------------------------------------------------------

    @staticmethod
    def _row_to_user(row: dict[str, Any]) -> User:
        verified = row.get("email_verified_at")
        return User(
            id=row["id"],
            username=row["username"],
            email=row.get("email"),
            owner_id=row.get("owner_id"),
            email_verified_at=None if verified is None else datetime.fromisoformat(verified),
            status=UserStatus(row.get("status") or UserStatus.ACTIVE.value),
            is_admin=bool(row["is_admin"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_token(row: dict[str, Any]) -> ApiToken:
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


__all__ = ["EmailTaken", "UserNotFound", "UserStoreMixin", "UsernameTaken"]
