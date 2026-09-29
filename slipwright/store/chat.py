"""Chat links, link codes and the questions put to people: mixed into ``JobStore``.

Rows only. ``slipwright/notify`` decides what a press means and whether it is allowed;
the one rule kept here is that an account on a chat service belongs to one person per
bot -- linking it again moves it, it never answers for two people at once.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select, update

from slipwright.notify.models import ChatLink, ChatPrompt
from slipwright.schemas.job import new_job_id, utcnow
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import chat_codes, chat_links, chat_prompts, settings

#: Letters a person can read off one screen and type on another without a mistake: no
#: 0/O, no 1/I/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


class ChatStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    # -- codes -------------------------------------------------------------------------

    def create_chat_code(self, owner_id: str, user_id: str, *, ttl: timedelta) -> str:
        """A fresh code for this person; any earlier one stops working."""
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        now = utcnow()
        with self.db.begin() as conn:
            conn.execute(
                delete(chat_codes).where(
                    chat_codes.c.owner_id == owner_id, chat_codes.c.user_id == user_id
                )
            )
            conn.execute(
                insert(chat_codes).values(
                    code_hash=_hash(code),
                    owner_id=owner_id,
                    user_id=user_id,
                    created_at=now.isoformat(),
                    expires_at=(now + ttl).isoformat(),
                )
            )
        return code

    def redeem_chat_code(self, owner_id: str, code: str) -> str | None:
        """Whose code this is, once: a code is spent by being read. ``None`` when it is
        unknown, belongs to another account's bot, or has run out."""
        with self.db.begin() as conn:
            row = one(
                conn.execute(
                    select(chat_codes).where(
                        chat_codes.c.code_hash == _hash(code), chat_codes.c.owner_id == owner_id
                    )
                )
            )
            if row is None:
                return None
            conn.execute(delete(chat_codes).where(chat_codes.c.code_hash == row["code_hash"]))
        if datetime.fromisoformat(row["expires_at"]) < utcnow():
            return None
        return str(row["user_id"])

    # -- links -------------------------------------------------------------------------

    def save_chat_link(self, link: ChatLink) -> ChatLink:
        with self.db.begin() as conn:
            # one account per person per service, and one person per account
            conn.execute(
                delete(chat_links).where(
                    chat_links.c.owner_id == link.owner_id,
                    chat_links.c.channel == link.channel,
                    (chat_links.c.user_id == link.user_id)
                    | (chat_links.c.external_id == link.external_id),
                )
            )
            conn.execute(
                insert(chat_links).values(
                    id=link.id,
                    owner_id=link.owner_id,
                    user_id=link.user_id,
                    channel=link.channel,
                    external_id=link.external_id,
                    address_json=json.dumps(link.address),
                    label=link.label,
                    linked_at=link.linked_at.isoformat(),
                )
            )
        return link

    def chat_links(
        self, owner_id: str, *, channel: str | None = None, user_id: str | None = None
    ) -> list[ChatLink]:
        query = select(chat_links).where(chat_links.c.owner_id == owner_id)
        if channel is not None:
            query = query.where(chat_links.c.channel == channel)
        if user_id is not None:
            query = query.where(chat_links.c.user_id == user_id)
        with self.db.connect() as conn:
            return [_link(r) for r in rows(conn.execute(query.order_by(chat_links.c.linked_at)))]

    def chat_link_for(self, owner_id: str, channel: str, external_id: str) -> ChatLink | None:
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(chat_links).where(
                        chat_links.c.owner_id == owner_id,
                        chat_links.c.channel == channel,
                        chat_links.c.external_id == external_id,
                    )
                )
            )
        return None if row is None else _link(row)

    def delete_chat_link(self, owner_id: str, channel: str, user_id: str) -> bool:
        with self.db.begin() as conn:
            result = conn.execute(
                delete(chat_links).where(
                    chat_links.c.owner_id == owner_id,
                    chat_links.c.channel == channel,
                    chat_links.c.user_id == user_id,
                )
            )
        return bool(result.rowcount)

    # -- prompts -----------------------------------------------------------------------

    def add_chat_prompt(
        self,
        *,
        owner_id: str,
        user_id: str,
        channel: str,
        external_id: str,
        job_id: str,
        marker: str,
        address: dict[str, Any],
    ) -> ChatPrompt:
        prompt = ChatPrompt(
            # what the buttons carry: long enough not to be guessed, short enough for the
            # 64 bytes Telegram allows a button
            id=secrets.token_hex(12),
            owner_id=owner_id,
            user_id=user_id,
            channel=channel,
            external_id=external_id,
            job_id=job_id,
            marker=marker,
            address=address,
            created_at=utcnow(),
        )
        with self.db.begin() as conn:
            conn.execute(
                insert(chat_prompts).values(
                    id=prompt.id,
                    owner_id=owner_id,
                    user_id=user_id,
                    channel=channel,
                    external_id=external_id,
                    job_id=job_id,
                    marker=marker,
                    address_json=json.dumps(address),
                    ref_json="{}",
                    status="open",
                    created_at=prompt.created_at.isoformat(),
                )
            )
        return prompt

    def get_chat_prompt(self, prompt_id: str) -> ChatPrompt | None:
        with self.db.connect() as conn:
            row = one(conn.execute(select(chat_prompts).where(chat_prompts.c.id == prompt_id)))
        return None if row is None else _prompt(row)

    def set_chat_prompt(
        self, prompt_id: str, *, status: str | None = None, ref: dict[str, Any] | None = None
    ) -> None:
        values: dict[str, Any] = {}
        if status is not None:
            values["status"] = status
            if status in ("approved", "rejected", "retried", "closed"):
                values["decided_at"] = utcnow().isoformat()
        if ref is not None:
            values["ref_json"] = json.dumps(ref)
        if not values:
            return
        with self.db.begin() as conn:
            conn.execute(update(chat_prompts).where(chat_prompts.c.id == prompt_id).values(values))

    def claim_chat_prompt(self, prompt_id: str, frm: tuple[str, ...], to: str) -> bool:
        """Move a prompt on only if it is still where the caller saw it. Two presses of the
        same button -- a double tap, two devices -- race here, and one of them loses."""
        with self.db.begin() as conn:
            result = conn.execute(
                update(chat_prompts)
                .where(chat_prompts.c.id == prompt_id, chat_prompts.c.status.in_(frm))
                .values(
                    status=to,
                    decided_at=(
                        utcnow().isoformat()
                        if to in ("approved", "rejected", "retried", "closed")
                        else None
                    ),
                )
            )
        return bool(result.rowcount)

    def open_chat_prompts(self, job_id: str) -> list[ChatPrompt]:
        """Every question about this development that nobody has answered yet."""
        with self.db.connect() as conn:
            found = rows(
                conn.execute(
                    select(chat_prompts).where(
                        chat_prompts.c.job_id == job_id,
                        chat_prompts.c.status.in_(("open", "reason")),
                    )
                )
            )
        return [_prompt(r) for r in found]

    def chat_prompt_awaiting_reason(
        self, owner_id: str, channel: str, external_id: str
    ) -> ChatPrompt | None:
        """The rejection this person started and has not yet said why for, newest first."""
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(chat_prompts)
                    .where(
                        chat_prompts.c.owner_id == owner_id,
                        chat_prompts.c.channel == channel,
                        chat_prompts.c.external_id == external_id,
                        chat_prompts.c.status == "reason",
                    )
                    .order_by(chat_prompts.c.created_at.desc())
                )
            )
        return None if row is None else _prompt(row)

    # -- who has set something up --------------------------------------------------------

    def owners_with_setting(self, name: str) -> list[str]:
        """Every account that has this setting stored: the listeners start one bot each."""
        with self.db.connect() as conn:
            return [
                str(r["user_id"])
                for r in rows(
                    conn.execute(select(settings.c.user_id).where(settings.c.name == name))
                )
            ]


def _link(row: dict[str, Any]) -> ChatLink:
    return ChatLink(
        id=row["id"],
        owner_id=row["owner_id"],
        user_id=row["user_id"],
        channel=row["channel"],
        external_id=row["external_id"],
        address=json.loads(row["address_json"] or "{}"),
        label=row["label"] or "",
        linked_at=datetime.fromisoformat(row["linked_at"]),
    )


def _prompt(row: dict[str, Any]) -> ChatPrompt:
    return ChatPrompt(
        id=row["id"],
        owner_id=row["owner_id"],
        user_id=row["user_id"],
        channel=row["channel"],
        external_id=row["external_id"],
        job_id=row["job_id"],
        marker=row["marker"],
        address=json.loads(row["address_json"] or "{}"),
        ref=json.loads(row["ref_json"] or "{}"),
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        decided_at=datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None,
    )


def new_link_id() -> str:
    return new_job_id()


__all__ = ["ChatStoreMixin", "new_link_id"]
