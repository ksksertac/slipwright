"""Slack: an incoming webhook for the group, and an app in Socket Mode for the buttons.

Socket Mode is the Slack equivalent of Telegram's long polling: the server opens a
websocket *to* Slack and the presses arrive over it, so no public URL is needed. It takes
two tokens -- the app-level one (``xapp-``, scope ``connections:write``) that opens the
socket, and the bot one (``xoxb-``, scopes ``chat:write`` and ``im:history``) that posts.

Rejecting opens a modal with one text field; what is typed there is the feedback.
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

API = "https://slack.com/api"
REJECT_VIEW = "slipwright_reject"
#: A button's action id, and the press it stands for.
PRESSES = {"sw_approve": "approve", "sw_reject": "reject", "sw_retry": "retry"}


def _escape(text: str) -> str:
    """Slack reads ``&``, ``<`` and ``>`` as markup; an agent's text must not be."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _mrkdwn(msg: Message, lang: str) -> str:
    body = _escape(msg.text(with_link=False))
    if msg.link:
        body += f"\n<{msg.link}|{word(lang, 'open')} →>"
    return body


class SlackAdapter:
    channel = "slack"

    def __init__(
        self, webhook: str, bot_token: str, app_token: str, http: HttpFactory, lang: str = "tr"
    ) -> None:
        self.webhook = webhook.strip()
        self.bot_token = bot_token.strip()
        self.app_token = app_token.strip()
        self.http = http
        self.lang = lang

    @property
    def has_group(self) -> bool:
        return bool(self.webhook)

    @property
    def has_bot(self) -> bool:
        return bool(self.bot_token and self.app_token)

    def call(self, method: str, payload: dict[str, Any], *, token: str | None = None) -> Any:
        try:
            with self.http() as client:
                response = client.post(
                    f"{API}/{method}",
                    json=payload,
                    headers={"Authorization": f"Bearer {token or self.bot_token}"},
                    timeout=15.0,
                )
        except httpx.HTTPError as exc:
            raise NotifyError(f"slack {method}: {exc}") from exc
        body = check(response, f"slack {method}")
        if not body.get("ok"):
            raise NotifyError(f"slack {method}: {body.get('error', 'refused')}")
        return body

    # -- out -------------------------------------------------------------------------------

    def post_group(self, msg: Message) -> None:
        try:
            with self.http() as client:
                response = client.post(
                    self.webhook, json={"text": _mrkdwn(msg, self.lang)}, timeout=15.0
                )
        except httpx.HTTPError as exc:
            raise NotifyError(f"slack webhook: {exc}") from exc
        if response.status_code >= 400:
            raise NotifyError(f"slack webhook: HTTP {response.status_code}: {response.text[:200]}")

    def ask(self, address: dict[str, Any], msg: Message, prompt_id: str) -> dict[str, Any]:
        text = _mrkdwn(msg, self.lang)
        body = self.call(
            "chat.postMessage",
            {
                # a user id as the channel is the app's own conversation with that person
                "channel": address.get("channel") or address["user"],
                "text": msg.summary or msg.headline,
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                    {
                        "type": "actions",
                        "block_id": "slipwright",
                        "elements": self._buttons(msg, prompt_id),
                    },
                ],
            },
        )
        return {"channel": body.get("channel"), "ts": body.get("ts"), "text": text}

    def _buttons(self, msg: Message, prompt_id: str) -> list[dict[str, Any]]:
        def button(action: str, style: str, label: str) -> dict[str, Any]:
            return {
                "type": "button",
                "action_id": action,
                "style": style,
                "text": {"type": "plain_text", "text": word(self.lang, label)},
                "value": prompt_id,
            }

        if msg.kind == "failed":
            return [button("sw_retry", "primary", "retry")]
        return [
            button("sw_approve", "primary", "approve"),
            button("sw_reject", "danger", "reject"),
        ]

    def settle(self, address: dict[str, Any], ref: dict[str, Any], outcome: str) -> None:
        if not ref.get("ts"):
            return
        text = settled_text(str(ref.get("text", "")), _escape(outcome))
        self.call(
            "chat.update",
            {
                "channel": ref.get("channel") or address.get("channel"),
                "ts": ref["ts"],
                "text": outcome,
                "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
            },
        )

    def say(self, address: dict[str, Any], text: str) -> None:
        self.call(
            "chat.postMessage",
            {"channel": address.get("channel") or address["user"], "text": _escape(text)},
        )

    def ask_reason(self, trigger_id: str, prompt_id: str) -> None:
        self.call(
            "views.open",
            {
                "trigger_id": trigger_id,
                "view": {
                    "type": "modal",
                    "callback_id": REJECT_VIEW,
                    "private_metadata": prompt_id,
                    "title": {"type": "plain_text", "text": word(self.lang, "reject")[:24]},
                    "submit": {"type": "plain_text", "text": word(self.lang, "reject")[:24]},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "reason",
                            "label": {"type": "plain_text", "text": word(self.lang, "why_short")},
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "reason",
                                "multiline": True,
                            },
                        }
                    ],
                },
            },
        )

    # -- setup -----------------------------------------------------------------------------

    def socket_url(self) -> str:
        body = self.call("apps.connections.open", {}, token=self.app_token)
        return str(body["url"])

    def identity(self) -> dict[str, Any]:
        body: dict[str, Any] = self.call("auth.test", {})
        return body


def handle_envelope(
    notifier: Notifier, adapter: SlackAdapter, envelope: dict[str, Any]
) -> dict[str, Any] | None:
    """One Socket Mode envelope. Returns the payload the acknowledgement carries, if any:
    a modal that did not work stays open with the reason under its field."""
    payload = envelope.get("payload") or {}
    kind = envelope.get("type")

    if kind == "events_api":
        event = payload.get("event") or {}
        if (
            event.get("type") == "message"
            and event.get("channel_type") == "im"
            and not event.get("bot_id")
            and not event.get("subtype")
            and event.get("user")
        ):
            address = {"user": event["user"], "channel": event.get("channel")}
            reply = notifier.on_text(
                "slack",
                external_id=str(event["user"]),
                address=address,
                label=str(event["user"]),
                text=str(event.get("text") or ""),
            )
            if reply is not None and reply.text:
                adapter.say(address, reply.text)
        return None

    if kind != "interactive":
        return None
    who = str((payload.get("user") or {}).get("id", ""))

    if payload.get("type") == "block_actions":
        actions = payload.get("actions") or []
        if not actions:
            return None
        action = actions[0]
        pressed = PRESSES.get(str(action.get("action_id") or ""))
        if pressed is None:
            return None
        prompt_id = str(action.get("value") or "")
        reply = notifier.on_press("slack", external_id=who, prompt_id=prompt_id, action=pressed)
        if reply.ask_reason and payload.get("trigger_id"):
            adapter.ask_reason(str(payload["trigger_id"]), prompt_id)
        elif not reply.final:
            channel = (payload.get("channel") or {}).get("id") or who
            adapter.say({"user": who, "channel": channel}, reply.text)
        return None

    if payload.get("type") == "view_submission":
        view = payload.get("view") or {}
        if view.get("callback_id") != REJECT_VIEW:
            return None
        values = ((view.get("state") or {}).get("values") or {}).get("reason") or {}
        reason = str((values.get("reason") or {}).get("value") or "").strip()
        reply = notifier.on_press(
            "slack",
            external_id=who,
            prompt_id=str(view.get("private_metadata") or ""),
            action="reject",
            reason=reason,
        )
        if reply.final:
            return None  # an empty acknowledgement closes the modal
        return {"response_action": "errors", "errors": {"reason": reply.text}}
    return None


__all__ = ["REJECT_VIEW", "SlackAdapter", "handle_envelope"]
