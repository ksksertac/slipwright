"""What every chat channel offers the notifier, and the error they all raise.

A channel does two different jobs and may be set up for either or both:

* **the group** -- one place the whole team reads. It is told, and nothing more: a button
  there could be pressed by anybody in the room, and the only people who may approve a
  gate are its owner and whoever holds that gate's agent.
* **the bot** -- a conversation with one person who has proven the chat account is
  theirs. That is where "carry on / reject" is asked, because a press there arrives
  carrying an id that was linked to exactly one Slipwright account.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx

from slipwright.notify.text import Message

HttpFactory = Callable[[], httpx.Client]


class NotifyError(RuntimeError):
    """A chat service refused or could not be reached. Never stops a development."""


class Adapter(Protocol):
    channel: str

    @property
    def has_group(self) -> bool: ...

    @property
    def has_bot(self) -> bool: ...

    def post_group(self, msg: Message) -> None: ...

    def ask(self, address: dict[str, Any], msg: Message, prompt_id: str) -> dict[str, Any]:
        """Send the question with its two buttons; returns what ``settle`` needs to find
        the message again."""
        ...

    def settle(self, address: dict[str, Any], ref: dict[str, Any], outcome: str) -> None:
        """Replace the buttons with what became of the question."""
        ...

    def say(self, address: dict[str, Any], text: str) -> None: ...


def check(response: httpx.Response, what: str) -> dict[str, Any]:
    """The JSON body of a call that must have worked, or a ``NotifyError`` saying why."""
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    if response.status_code >= 400:
        detail = body if body is not None else response.text[:300]
        raise NotifyError(f"{what}: HTTP {response.status_code}: {detail}")
    return body if isinstance(body, dict) else {}


def settled_text(original: str, outcome: str) -> str:
    return f"{original}\n\n{outcome}" if original else outcome


__all__ = ["Adapter", "HttpFactory", "NotifyError", "check", "settled_text"]
