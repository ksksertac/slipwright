"""Microsoft Teams: a Workflows webhook for the group, and an Azure bot for the buttons.

Teams is the one channel that cannot pull. Microsoft *pushes* every message and every
press to the bot's messaging endpoint, so this half needs a public HTTPS address --
``<base url>/api/notify/inbound/teams/<account>`` -- and an Azure Bot registration (an app
id, a client secret, and for a single-tenant bot the tenant id).

Because anybody on the internet can reach that endpoint, nothing it receives is believed
until the request's bearer token has been verified: signed by one of Microsoft's published
keys, issued by the Bot Framework, addressed to this bot's app id, still in date, and
naming the same service URL the activity says it came from. That check is
``verify_token``; the endpoint refuses before reading the body when it fails.

The question is an Adaptive Card with a text field and two buttons, so a rejection and
its reason arrive in one press.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from slipwright.notify.base import HttpFactory, NotifyError, check, settled_text
from slipwright.notify.text import Message, word

if TYPE_CHECKING:
    from slipwright.notify.core import Notifier

log = logging.getLogger(__name__)

OPENID = "https://login.botframework.com/v1/.well-known/openidconfiguration"
ISSUER = "https://api.botframework.com"
SCOPE = "https://api.botframework.com/.default"
#: Clocks drift; Microsoft's own libraries allow five minutes either way.
SKEW_S = 300


def _card(body: list[dict[str, Any]], actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "contentUrl": None,
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
            "actions": actions,
        },
    }


def _blocks(msg: Message) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": msg.headline, "weight": "Bolder", "wrap": True}
    ]
    out += [
        {"type": "TextBlock", "text": line, "wrap": True, "spacing": "Small"} for line in msg.lines
    ]
    return out


def _open(msg: Message, lang: str) -> list[dict[str, Any]]:
    # Teams refuses a card whose link is not https; a local install's link is left in text
    if msg.link and msg.link.startswith("https://"):
        return [{"type": "Action.OpenUrl", "title": word(lang, "open"), "url": msg.link}]
    return []


class TeamsAdapter:
    channel = "teams"

    def __init__(
        self,
        webhook: str,
        app_id: str,
        app_password: str,
        tenant_id: str,
        http: HttpFactory,
        lang: str = "tr",
    ) -> None:
        self.webhook = webhook.strip()
        self.app_id = app_id.strip()
        self.app_password = app_password.strip()
        self.tenant_id = tenant_id.strip()
        self.http = http
        self.lang = lang
        self._token: tuple[str, float] | None = None

    @property
    def has_group(self) -> bool:
        return bool(self.webhook)

    @property
    def has_bot(self) -> bool:
        return bool(self.app_id and self.app_password)

    # -- the bot's own token -----------------------------------------------------------------

    def token(self) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        # a single-tenant bot is issued its token by its own tenant; a multi-tenant one by
        # the Bot Framework's
        tenant = self.tenant_id or "botframework.com"
        try:
            with self.http() as client:
                response = client.post(
                    f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.app_id,
                        "client_secret": self.app_password,
                        "scope": SCOPE,
                    },
                    timeout=15.0,
                )
        except httpx.HTTPError as exc:
            raise NotifyError(f"teams token: {exc}") from exc
        body = check(response, "teams token")
        token = str(body.get("access_token") or "")
        if not token:
            raise NotifyError("teams token: no access_token in the answer")
        self._token = (token, time.time() + float(body.get("expires_in") or 3000))
        return token

    def _activity(self, method: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.http() as client:
                response = client.request(
                    method,
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.token()}"},
                    timeout=15.0,
                )
        except httpx.HTTPError as exc:
            raise NotifyError(f"teams activity: {exc}") from exc
        return check(response, "teams activity")

    @staticmethod
    def _conversation(address: dict[str, Any]) -> str:
        service = str(address["service_url"]).rstrip("/")
        return f"{service}/v3/conversations/{address['conversation']}/activities"

    # -- out -------------------------------------------------------------------------------

    def post_group(self, msg: Message) -> None:
        payload = {
            "type": "message",
            "attachments": [_card(_blocks(msg), _open(msg, self.lang))],
        }
        try:
            with self.http() as client:
                response = client.post(self.webhook, json=payload, timeout=15.0)
        except httpx.HTTPError as exc:
            raise NotifyError(f"teams webhook: {exc}") from exc
        if response.status_code >= 400:
            raise NotifyError(f"teams webhook: HTTP {response.status_code}: {response.text[:200]}")

    def ask(self, address: dict[str, Any], msg: Message, prompt_id: str) -> dict[str, Any]:
        body = [
            *_blocks(msg),
            {
                "type": "Input.Text",
                "id": "reason",
                "isMultiline": True,
                "placeholder": word(self.lang, "why"),
            },
        ]
        actions = [
            {
                "type": "Action.Submit",
                "title": word(self.lang, "approve"),
                "style": "positive",
                "data": {"sw": "a", "p": prompt_id},
            },
            {
                "type": "Action.Submit",
                "title": word(self.lang, "reject"),
                "style": "destructive",
                "data": {"sw": "r", "p": prompt_id},
            },
            *_open(msg, self.lang),
        ]
        sent = self._activity(
            "POST",
            self._conversation(address),
            {"type": "message", "summary": msg.summary, "attachments": [_card(body, actions)]},
        )
        return {"activity_id": sent.get("id"), "text": msg.text()}

    def settle(self, address: dict[str, Any], ref: dict[str, Any], outcome: str) -> None:
        if not ref.get("activity_id"):
            return
        self._activity(
            "PUT",
            f"{self._conversation(address)}/{ref['activity_id']}",
            {
                "type": "message",
                "id": ref["activity_id"],
                "text": settled_text(str(ref.get("text", "")), outcome).replace("\n", "\n\n"),
            },
        )

    def say(self, address: dict[str, Any], text: str) -> None:
        self._activity("POST", self._conversation(address), {"type": "message", "text": text})


# -- verifying what Microsoft sends -------------------------------------------------------------

_keys_lock = threading.Lock()
_keys: dict[str, Any] = {"at": 0.0, "keys": {}}
#: Microsoft rotates its signing keys rarely and announces them ahead; a day is the
#: refresh its own libraries use.
KEYS_TTL_S = 86_400


def _b64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _signing_keys(http: HttpFactory, *, refresh: bool = False) -> dict[str, dict[str, Any]]:
    with _keys_lock:
        if not refresh and _keys["keys"] and time.time() - _keys["at"] < KEYS_TTL_S:
            return dict(_keys["keys"])
    try:
        with http() as client:
            config = client.get(OPENID, timeout=10.0).json()
            jwks = client.get(str(config["jwks_uri"]), timeout=10.0).json()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise NotifyError(f"teams: could not read Microsoft's signing keys: {exc}") from exc
    keys = {str(k["kid"]): k for k in jwks.get("keys", []) if k.get("kid")}
    with _keys_lock:
        _keys["keys"] = keys
        _keys["at"] = time.time()
    return keys


def verify_token(
    authorization: str | None, *, app_id: str, service_url: str, http: HttpFactory
) -> dict[str, Any]:
    """The claims of a genuine Bot Framework request, or ``NotifyError`` saying why not."""
    if not authorization or not authorization.startswith("Bearer "):
        raise NotifyError("no bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        header = json.loads(_b64(head_b64))
        claims: dict[str, Any] = json.loads(_b64(body_b64))
        signature = _b64(sig_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise NotifyError("malformed token") from exc
    if header.get("alg") != "RS256":
        raise NotifyError(f"unexpected algorithm {header.get('alg')!r}")
    kid = str(header.get("kid") or "")
    keys = _signing_keys(http)
    if kid not in keys:
        keys = _signing_keys(http, refresh=True)  # a key rotated since the last read
    jwk = keys.get(kid)
    if jwk is None:
        raise NotifyError("token signed by an unknown key")
    public = rsa.RSAPublicNumbers(
        int.from_bytes(_b64(jwk["e"]), "big"), int.from_bytes(_b64(jwk["n"]), "big")
    ).public_key()
    try:
        public.verify(
            signature,
            f"{head_b64}.{body_b64}".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise NotifyError("bad signature") from exc
    now = time.time()
    if claims.get("iss") != ISSUER:
        raise NotifyError("not issued by the Bot Framework")
    if claims.get("aud") != app_id:
        raise NotifyError("addressed to another bot")
    if float(claims.get("exp", 0)) < now - SKEW_S:
        raise NotifyError("expired")
    if float(claims.get("nbf", 0)) > now + SKEW_S:
        raise NotifyError("not valid yet")
    claimed = str(claims.get("serviceurl") or claims.get("serviceUrl") or "")
    if claimed and claimed.rstrip("/") != service_url.rstrip("/"):
        raise NotifyError("service URL does not match the token")
    return claims


def _plain(text: str) -> str:
    """A Teams message as a person typed it: without the mention of the bot, without tags."""
    import re

    text = re.sub(r"<at>.*?</at>", "", text)
    return re.sub(r"<[^>]+>", "", text).strip()


def handle_activity(notifier: Notifier, adapter: TeamsAdapter, activity: dict[str, Any]) -> None:
    """One verified activity: something typed to the bot, or a card's button pressed."""
    if activity.get("type") != "message":
        return
    sender = activity.get("from") or {}
    who = str(sender.get("aadObjectId") or sender.get("id") or "")
    address = {
        "service_url": activity.get("serviceUrl"),
        "conversation": (activity.get("conversation") or {}).get("id"),
        "user": who,
    }
    value = activity.get("value")
    if isinstance(value, dict) and value.get("sw") in ("a", "r"):
        reply = notifier.on_press(
            "teams",
            external_id=who,
            prompt_id=str(value.get("p") or ""),
            action="approve" if value["sw"] == "a" else "reject",
            reason=str(value.get("reason") or "").strip() or None,
        )
        if reply.ask_reason:
            adapter.say(address, word(notifier.lang, "empty_reason"))
        elif not reply.final:
            adapter.say(address, reply.text)
        return
    said = notifier.on_text(
        "teams",
        external_id=who,
        address=address,
        label=str(sender.get("name") or ""),
        text=_plain(str(activity.get("text") or "")),
    )
    if said is not None and said.text:
        adapter.say(address, said.text)


__all__ = ["TeamsAdapter", "handle_activity", "verify_token"]
