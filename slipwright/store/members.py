"""Who is on which agent: the ``agent_members`` table, mixed into ``JobStore``.

Nothing here decides anything. It reads and writes rows; ``slipwright/teams.py`` decides
what a row means, and the API decides who may ask. The one rule the table itself keeps is
that a membership is never deleted -- it ends, with a date and a word for how -- so the
list an owner reads is the whole story and an invited address stays taken.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import insert, select, update

from slipwright.auth import User
from slipwright.schemas.job import utcnow
from slipwright.schemas.profile import RoleName
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import agent_members
from slipwright.teams import Membership, MemberStatus


class MemberStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    def add_membership(self, membership: Membership) -> Membership:
        with self.db.begin() as conn:
            conn.execute(insert(agent_members).values(**_to_row(membership)))
        return membership

    def get_membership(self, membership_id: str) -> Membership | None:
        with self.db.connect() as conn:
            row = one(
                conn.execute(select(agent_members).where(agent_members.c.id == membership_id))
            )
        return None if row is None else _to_membership(row)

    def find_membership(self, owner_id: str, role: RoleName, email: str) -> Membership | None:
        """The newest row for this person on this agent, whatever became of it."""
        query = (
            select(agent_members)
            .where(
                agent_members.c.owner_id == owner_id,
                agent_members.c.role == role.value,
                agent_members.c.email == email.strip().lower(),
            )
            .order_by(agent_members.c.invited_at.desc())
        )
        with self.db.connect() as conn:
            found = rows(conn.execute(query))
        return _to_membership(found[0]) if found else None

    def list_members(self, owner_id: str, role: RoleName | None = None) -> list[Membership]:
        """Everyone this account has ever put on an agent, oldest invitation first."""
        query = select(agent_members).where(agent_members.c.owner_id == owner_id)
        if role is not None:
            query = query.where(agent_members.c.role == role.value)
        query = query.order_by(agent_members.c.invited_at, agent_members.c.id)
        with self.db.connect() as conn:
            found = rows(conn.execute(query))
        return [_to_membership(r) for r in found]

    def memberships_of(self, user_id: str) -> list[Membership]:
        query = (
            select(agent_members)
            .where(agent_members.c.user_id == user_id)
            .order_by(agent_members.c.invited_at, agent_members.c.id)
        )
        with self.db.connect() as conn:
            found = rows(conn.execute(query))
        return [_to_membership(r) for r in found]

    def agents_of(self, user_id: str) -> set[RoleName]:
        """The agents this person may act as right now. The authorisation answer."""
        return {
            m.role
            for m in self.memberships_of(user_id)
            if m.status is MemberStatus.ACTIVE
        }

    def set_membership_status(self, membership_id: str, status: MemberStatus) -> Membership:
        now = utcnow().isoformat()
        values: dict[str, Any] = {"status": status.value}
        if status is MemberStatus.ACTIVE or status is MemberStatus.DECLINED:
            values["responded_at"] = now
        if status.over:
            values["ended_at"] = now
        with self.db.begin() as conn:
            changed = conn.execute(
                update(agent_members).where(agent_members.c.id == membership_id).values(**values)
            )
            if changed.rowcount == 0:
                raise KeyError(f"membership not found: {membership_id}")
        found = self.get_membership(membership_id)
        assert found is not None
        return found

    def create_invited_user(self, email: str, *, owner_id: str, name: str = "") -> User:
        """An account for somebody who has not answered yet.

        It exists so the address is taken and the letter has something to point at. There
        is no password anybody knows: a random one is stored, and the invitation replaces
        it. ``UserStatus.INVITED`` keeps it out of every login until then.
        """
        from slipwright.auth import UserStatus, new_secret  # local: store/users.py owns these

        address = email.strip().lower()
        username = (name or address.split("@")[0]).strip()
        candidate, n = username, 1
        while self.find_user(candidate) is not None:  # type: ignore[attr-defined]
            n += 1
            candidate = f"{username} ({n})"
        return self.create_user(  # type: ignore[attr-defined,no-any-return]
            candidate,
            new_secret(),
            is_admin=False,
            email=address,
            owner_id=owner_id,
            status=UserStatus.INVITED,
        )


def _to_row(m: Membership) -> dict[str, Any]:
    return {
        "id": m.id,
        "owner_id": m.owner_id,
        "role": m.role.value,
        "user_id": m.user_id,
        "email": m.email,
        "name": m.name,
        "status": m.status.value,
        "invited_by": m.invited_by,
        "invited_at": m.invited_at.isoformat(),
        "responded_at": None if m.responded_at is None else m.responded_at.isoformat(),
        "ended_at": None if m.ended_at is None else m.ended_at.isoformat(),
    }


def _to_membership(row: dict[str, Any]) -> Membership:
    def when(value: str | None) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)

    return Membership(
        id=row["id"],
        owner_id=row["owner_id"],
        role=RoleName(row["role"]),
        user_id=row["user_id"],
        email=row["email"],
        name=row["name"] or "",
        status=MemberStatus(row["status"]),
        invited_by=row["invited_by"],
        invited_at=datetime.fromisoformat(row["invited_at"]),
        responded_at=when(row["responded_at"]),
        ended_at=when(row["ended_at"]),
    )


__all__ = ["MemberStoreMixin"]
