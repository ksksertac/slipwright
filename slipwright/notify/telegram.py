"""Telegram: a bot token, and optionally the id of a group the bot has been added to.

The bot *pulls* its updates (``getUpdates``, long polling) rather than having them pushed
to a webhook. That one choice is why Telegram is the channel that works on a laptop: the
server needs no public address for a button press to reach it.

Linking uses Telegram's own deep link, ``t.me/<bot>?start=<code>``: opening it sends
``/start <code>`` from the person's account, and the id that message carries is what
every later press is checked against.
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import TYPE_CHECKING, Any

import httpx

from slipwright.notify.ask import PRESS, decide
from slipwright.notify.base import HttpFactory, NotifyError, settled_text
from slipwright.notify.text import Message, word

if TYPE_CHECKING:
    from slipwright.notify.core import Notifier, Reply

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
#: Telegram refuses a message longer than this; a long plan summary is clipped, not lost:
#: the link is still there.
LIMIT = 4000


class TelegramAdapter:
    channel = "telegram"

    def __init__(self, token: str, group_chat_id: str, http: HttpFactory, lang: str = "tr") -> None:
        self.token = token.strip()
        self.group_chat_id = group_chat_id.strip()
        self.http = http
        self.lang = lang

    @property
    def has_group(self) -> bool:
        return bool(self.token and self.group_chat_id)

    @property
    def has_bot(self) -> bool:
        return bool(self.token)

    def call(self, method: str, *, timeout: float = 15.0, **payload: Any) -> Any:
        try:
            with self.http() as client:
                response = client.post(
                    f"{API}/bot{self.token}/{method}", json=payload, timeout=timeout
                )
        except httpx.HTTPError as exc:
            raise NotifyError(f"telegram {method}: {exc}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise NotifyError(f"telegram {method}: HTTP {response.status_code}") from exc
        if not body.get("ok"):
            raise NotifyError(f"telegram {method}: {body.get('description', 'refused')}")
        return body.get("result")

    # -- out -------------------------------------------------------------------------------

    def send(self, chat_id: Any, text: str, **extra: Any) -> dict[str, Any]:
        result: dict[str, Any] = self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text[:LIMIT],
            disable_web_page_preview=True,
            **extra,
        )
        return result

    def post_group(self, msg: Message) -> None:
        self.send(self.group_chat_id, msg.text())

    def ask(self, address: dict[str, Any], msg: Message, prompt_id: str) -> dict[str, Any]:
        lang = self.lang
        text = msg.text()
        sent = self.send(
            address["chat_id"],
            text,
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": word(lang, "approve"), "callback_data": f"a:{prompt_id}"},
                        {"text": word(lang, "reject"), "callback_data": f"r:{prompt_id}"},
                    ]
                ]
            },
        )
        return {"chat_id": address["chat_id"], "message_id": sent.get("message_id"), "text": text}

    def settle(self, address: dict[str, Any], ref: dict[str, Any], outcome: str) -> None:
        if not ref.get("message_id"):
            return
        # editing the text without a reply_markup is what takes the buttons away
        self.call(
            "editMessageText",
            chat_id=ref.get("chat_id", address.get("chat_id")),
            message_id=ref["message_id"],
            text=settled_text(str(ref.get("text", "")), outcome)[:LIMIT],
            disable_web_page_preview=True,
        )

    def say(self, address: dict[str, Any], text: str) -> None:
        self.send(address["chat_id"], text)

    def ask_reason(self, chat_id: Any, lang: str) -> None:
        self.send(
            chat_id,
            word(lang, "why"),
            reply_markup={"force_reply": True, "input_field_placeholder": word(lang, "why_short")},
        )

    # -- setup -----------------------------------------------------------------------------

    def me(self) -> dict[str, Any]:
        result: dict[str, Any] = self.call("getMe")
        return result

    def updates(self, offset: int, *, wait_s: int = 25) -> list[dict[str, Any]]:
        # ``timeout`` is both Telegram's long-poll parameter and our HTTP timeout; they are
        # different numbers, so the call is spelled out rather than going through ``call``
        try:
            with self.http() as client:
                response = client.post(
                    f"{API}/bot{self.token}/getUpdates",
                    json={
                        "offset": offset,
                        "timeout": wait_s,
                        "allowed_updates": ["message", "callback_query"],
                    },
                    timeout=wait_s + 10.0,
                )
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise NotifyError(f"telegram getUpdates: {exc}") from exc
        if not body.get("ok"):
            raise NotifyError(f"telegram getUpdates: {body.get('description', 'refused')}")
        result: list[dict[str, Any]] = body.get("result") or []
        return result


_COMMAND = re.compile(r"^/(\w+)(?:@\w+)?(?:\s+(.*))?$", re.S)


def handle_update(notifier: Notifier, adapter: TelegramAdapter, update: dict[str, Any]) -> None:
    """One update from ``getUpdates``: a button pressed, or something typed to the bot."""
    lang = notifier.lang
    press = update.get("callback_query")
    if press:
        data = str(press.get("data") or "")
        who = str((press.get("from") or {}).get("id", ""))
        chat_id = ((press.get("message") or {}).get("chat") or {}).get("id")
        action, _, prompt_id = data.partition(":")
        if action == PRESS:
            # a question the bot asked of its own accord, not a gate: answered in
            # notify/ask.py, and the buttons come away so it cannot be answered twice
            answered = decide(notifier, external_id=who, choice=prompt_id)
            with contextlib.suppress(NotifyError):
                adapter.call(
                    "answerCallbackQuery", callback_query_id=press.get("id"), text=answered[:190]
                )
            if chat_id is not None and (press.get("message") or {}).get("message_id"):
                with contextlib.suppress(NotifyError):
                    adapter.call(
                        "editMessageReplyMarkup",
                        chat_id=chat_id,
                        message_id=(press.get("message") or {})["message_id"],
                    )
                adapter.send(chat_id, answered)
            return
        if action not in ("a", "r") or not prompt_id:
            return
        reply = notifier.on_press(
            "telegram",
            external_id=who,
            prompt_id=prompt_id,
            action="approve" if action == "a" else "reject",
        )
        try:
            adapter.call(
                "answerCallbackQuery", callback_query_id=press.get("id"), text=reply.text[:190]
            )
        except NotifyError as exc:
            log.info("telegram: could not answer a press: %s", exc)
        if reply.ask_reason and chat_id is not None:
            adapter.ask_reason(chat_id, lang)
        return

    message = update.get("message")
    if not message:
        return
    chat = message.get("chat") or {}
    text = str(message.get("text") or "").strip()
    if not text:
        return
    command = _COMMAND.match(text)
    if chat.get("type") != "private":
        # in a group the bot answers one question only: which group this is, which is
        # the number the settings page asks for
        if command and command.group(1) == "chatid":
            adapter.send(chat.get("id"), word(lang, "chat_id", id=chat.get("id")))
        return
    sender = message.get("from") or {}
    label = (
        f"@{sender['username']}" if sender.get("username") else str(sender.get("first_name", ""))
    )
    if command and command.group(1) == "chatid":
        adapter.send(chat.get("id"), word(lang, "chat_id", id=chat.get("id")))
        return
    said: Reply | None
    if command and command.group(1) in ("start", "link", "bagla", "bağla"):
        text = (command.group(2) or "").strip()
        if not text:
            adapter.send(chat.get("id"), word(lang, "hello"))
            return
        said = notifier.link(
            "telegram",
            code=text,
            external_id=str(sender.get("id", "")),
            address={"chat_id": chat.get("id")},
            label=label,
        )
    else:
        said = notifier.on_text(
            "telegram",
            external_id=str(sender.get("id", "")),
            address={"chat_id": chat.get("id")},
            label=label,
            text=text,
        )
    if said is not None and said.text:
        extra: dict[str, Any] = {}
        if said.buttons:
            extra["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": label, "callback_data": data} for label, data in said.buttons]
                ]
            }
        adapter.send(chat.get("id"), said.text, **extra)


__all__ = ["TelegramAdapter", "handle_update"]
