"""The shapes the notification tables hold. Kept free of imports so the store can use them."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Channel = Literal["telegram", "slack", "discord", "teams"]
CHANNELS: tuple[Channel, ...] = ("telegram", "slack", "discord", "teams")

#: What a group channel can be told about. A gate is the one that asks somebody for
#: something; the other two are news.
Event = Literal["gate", "failed", "done", "cancelled"]
EVENTS: tuple[Event, ...] = ("gate", "failed", "done", "cancelled")


class ChatLink(BaseModel):
    """A person's proven account on one chat service, under one account's bot."""

    id: str
    owner_id: str
    user_id: str
    channel: Channel
    external_id: str
    address: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    linked_at: datetime


class ChatPrompt(BaseModel):
    """One question sent to one person: "carry on or reject?" about one gate visit, or
    "try again?" about one failure. ``marker`` says which of the two, and which visit."""

    id: str
    owner_id: str
    user_id: str
    channel: Channel
    external_id: str
    job_id: str
    marker: str
    address: dict[str, Any] = Field(default_factory=dict)
    ref: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "reason", "approved", "rejected", "retried", "closed"] = "open"
    created_at: datetime
    decided_at: datetime | None = None

    @property
    def answered(self) -> bool:
        return self.status in ("approved", "rejected", "retried", "closed")


__all__ = ["CHANNELS", "EVENTS", "Channel", "ChatLink", "ChatPrompt", "Event"]
