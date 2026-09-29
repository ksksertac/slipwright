"""Discord: a channel webhook for the group, and a bot on the gateway for the buttons.

The bot connects to Discord's gateway (a websocket the server opens outward), so the
presses reach it without a public URL, the same way Slack's Socket Mode and Telegram's
long polling do. It asks only for ``DIRECT_MESSAGES``: a person links by sending the bot
the code in a direct message, and Discord delivers the text of a direct message to a bot
without the privileged message-content intent.

Rejecting opens a modal with one field; what is typed there is the feedback.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from slipwright.notify.base import HttpFactory, NotifyError, check, settled_text
from slipwright.notify.text import Message, word

if TYPE_CHECKING:
    from slipwright.notify.core import Notifier

log = logging.getLogger(__name__)

API = "https://discord.com/api/v10"
LIMIT = 2000
#: GUILD_MESSAGES is not needed; direct messages are the only text the bot reads.
INTENTS = 1 << 12  # DIRECT_MESSAGES

#: The middle of a button's custom id, and the press it stands for.
PRESSES = {"a": "approve", "r": "reject", "t": "retry"}

# interaction and response types, by their Discord numbers
PING, COMPONENT, MODAL_SUBMIT = 1, 3, 5
PONG, REPLY, DEFERRED_UPDATE, MODAL = 1, 4, 6, 9
EPHEMERAL = 1 << 6


class DiscordAdapter:
    channel = "discord"

    def __init__(self, webhook: str, bot_token: str, http: HttpFactory, lang: str = "tr") -> None:
        self.webhook = webhook.strip()
        self.bot_token = bot_token.strip()
        self.http = http
        self.lang = lang

    @property
    def has_group(self) -> bool:
        return bool(self.webhook)

    @property
    def has_bot(self) -> bool:
        return bool(self.bot_token)

    def call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            with self.http() as client:
                response = client.request(
                    method,
                    f"{API}{path}",
                    json=payload,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    timeout=15.0,
                )
        except httpx.HTTPError as exc:
            raise NotifyError(f"discord {path}: {exc}") from exc
        if response.status_code == 204:
            return {}
        return check(response, f"discord {path}")

    # -- out -------------------------------------------------------------------------------

    def post_group(self, msg: Message) -> None:
        try:
            with self.http() as client:
                response = client.post(
                    self.webhook,
                    # nobody is pinged by an agent's words, whatever they contain
                    json={"content": msg.text()[:LIMIT], "allowed_mentions": {"parse": []}},
                    timeout=15.0,
                )
        except httpx.HTTPError as exc:
            raise NotifyError(f"discord webhook: {exc}") from exc
        if response.status_code >= 400:
            raise NotifyError(
                f"discord webhook: HTTP {response.status_code}: {response.text[:200]}"
            )

    def _dm_channel(self, address: dict[str, Any]) -> str:
        if address.get("channel"):
            return str(address["channel"])
        body = self.call("POST", "/users/@me/channels", {"recipient_id": address["user"]})
        return str(body["id"])

    def ask(self, address: dict[str, Any], msg: Message, prompt_id: str) -> dict[str, Any]:
        channel = self._dm_channel(address)
        text = msg.text()[:LIMIT]
        body = self.call(
            "POST",
            f"/channels/{channel}/messages",
            {
                "content": text,
                "allowed_mentions": {"parse": []},
                "components": [{"type": 1, "components": self._buttons(msg, prompt_id)}],
            },
        )
        return {"channel": channel, "message_id": body.get("id"), "text": text}

    def _buttons(self, msg: Message, prompt_id: str) -> list[dict[str, Any]]:
        def button(style: int, label: str, action: str) -> dict[str, Any]:
            return {
                "type": 2,
                "style": style,
                "label": word(self.lang, label),
                "custom_id": f"sw:{action}:{prompt_id}",
            }

        if msg.kind == "failed":
            return [button(1, "retry", "t")]  # blurple
        return [button(3, "approve", "a"), button(4, "reject", "r")]  # green, red

    def settle(self, address: dict[str, Any], ref: dict[str, Any], outcome: str) -> None:
        if not ref.get("message_id"):
            return
        channel = ref.get("channel") or address.get("channel")
        self.call(
            "PATCH",
            f"/channels/{channel}/messages/{ref['message_id']}",
            {
                "content": settled_text(str(ref.get("text", "")), outcome)[:LIMIT],
                "components": [],
            },
        )

    def say(self, address: dict[str, Any], text: str) -> None:
        channel = self._dm_channel(address)
        self.call(
            "POST",
            f"/channels/{channel}/messages",
            {"content": text[:LIMIT], "allowed_mentions": {"parse": []}},
        )

    def respond(self, interaction: dict[str, Any], body: dict[str, Any]) -> None:
        """Answer an interaction. Discord allows three seconds and one answer."""
        try:
            with self.http() as client:
                response = client.post(
                    f"{API}/interactions/{interaction['id']}/{interaction['token']}/callback",
                    json=body,
                    timeout=10.0,
                )
        except httpx.HTTPError as exc:
            raise NotifyError(f"discord interaction: {exc}") from exc
        if response.status_code >= 400:
            raise NotifyError(
                f"discord interaction: HTTP {response.status_code}: {response.text[:200]}"
            )

    def reason_modal(self, prompt_id: str) -> dict[str, Any]:
        return {
            "type": MODAL,
            "data": {
                "custom_id": f"sw:m:{prompt_id}",
                "title": word(self.lang, "reject")[:45],
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 4,  # text input
                                "custom_id": "reason",
                                "style": 2,  # paragraph
                                "label": word(self.lang, "why_short")[:45],
                                "required": True,
                                "max_length": 2000,
                            }
                        ],
                    }
                ],
            },
        }

    # -- setup -----------------------------------------------------------------------------

    def gateway_url(self) -> str:
        body = self.call("GET", "/gateway/bot")
        return f"{body['url']}/?v=10&encoding=json"

    def identity(self) -> dict[str, Any]:
        body: dict[str, Any] = self.call("GET", "/users/@me")
        return body


def _modal_value(data: dict[str, Any]) -> str:
    for row in data.get("components") or []:
        for item in row.get("components") or []:
            if item.get("custom_id") == "reason":
                return str(item.get("value") or "").strip()
    return ""


def handle_dispatch(
    notifier: Notifier, adapter: DiscordAdapter, kind: str, data: dict[str, Any]
) -> None:
    """One gateway event: a direct message to the bot, or a press or modal of ours."""
    if kind == "MESSAGE_CREATE":
        author = data.get("author") or {}
        if data.get("guild_id") or author.get("bot"):
            return
        address = {"user": author.get("id"), "channel": data.get("channel_id")}
        reply = notifier.on_text(
            "discord",
            external_id=str(author.get("id", "")),
            address=address,
            label=str(author.get("global_name") or author.get("username") or ""),
            text=str(data.get("content") or ""),
        )
        if reply is not None and reply.text:
            adapter.say(address, reply.text)
        return

    if kind != "INTERACTION_CREATE":
        return
    user = data.get("user") or (data.get("member") or {}).get("user") or {}
    who = str(user.get("id", ""))
    custom = str((data.get("data") or {}).get("custom_id") or "")
    parts = custom.split(":")
    if len(parts) != 3 or parts[0] != "sw":
        return
    _, action, prompt_id = parts

    if data.get("type") == COMPONENT and action in PRESSES:
        reply = notifier.on_press(
            "discord", external_id=who, prompt_id=prompt_id, action=PRESSES[action]
        )
        if reply.ask_reason:
            adapter.respond(data, adapter.reason_modal(prompt_id))
        elif reply.final:
            # the message has already been rewritten; this only says "received"
            adapter.respond(data, {"type": DEFERRED_UPDATE})
        else:
            adapter.respond(
                data, {"type": REPLY, "data": {"content": reply.text, "flags": EPHEMERAL}}
            )
        return

    if data.get("type") == MODAL_SUBMIT and action == "m":
        reply = notifier.on_press(
            "discord",
            external_id=who,
            prompt_id=prompt_id,
            action="reject",
            reason=_modal_value(data.get("data") or {}),
        )
        if reply.final:
            adapter.respond(data, {"type": DEFERRED_UPDATE})
        else:
            adapter.respond(
                data, {"type": REPLY, "data": {"content": reply.text, "flags": EPHEMERAL}}
            )


__all__ = ["INTENTS", "DiscordAdapter", "handle_dispatch"]
