"""Notifications: agents reach people in Telegram, Slack, Discord and Teams (T13).

A fake of all four services sits behind ``httpx.MockTransport`` and records what was
sent. The listeners' network loops are not run; what they hand over -- an update, an
envelope, a gateway event, an activity -- is fed straight to the same handlers.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.mail import read_outbox
from slipwright.notify import msteams
from slipwright.notify.core import Notifier
from slipwright.notify.discord import DiscordAdapter, handle_dispatch
from slipwright.notify.slack import REJECT_VIEW, SlackAdapter, handle_envelope
from slipwright.notify.telegram import TelegramAdapter, handle_update
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider
from tests.test_phase12_teams import _accept, _invite, _sign_up_owner

BASE = "https://slipwright.example"
TG_TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
SLACK_HOOK = "https://hooks.slack.com/services/T0/B0/xyz"
DISCORD_HOOK = "https://discord.com/api/webhooks/1/abc"
TEAMS_HOOK = "https://prod.westeurope.logic.azure.com/workflows/abc"
TEAMS_APP = "11111111-2222-3333-4444-555555555555"
TEAMS_SERVICE = "https://smba.trafficmanager.net/emea/"


@dataclass
class Sent:
    method: str
    url: str
    body: Any


@dataclass
class FakeChat:
    """Every chat service at once. Answers like the real ones, remembers every call."""

    calls: list[Sent] = field(default_factory=list)
    jwks: dict[str, Any] = field(default_factory=lambda: {"keys": []})
    next_id: int = 100

    def __call__(self, request: httpx.Request) -> httpx.Response:
        raw = request.content.decode() if request.content else ""
        try:
            body: Any = json.loads(raw) if raw else None
        except ValueError:
            body = raw
        url = str(request.url)
        self.calls.append(Sent(request.method, url, body))
        self.next_id += 1
        host = request.url.host
        path = request.url.path
        if host == "api.telegram.org":
            method = path.rsplit("/", 1)[-1]
            if method == "getMe":
                return httpx.Response(200, json={"ok": True, "result": {"username": "swbot"}})
            if method == "sendMessage":
                return httpx.Response(
                    200, json={"ok": True, "result": {"message_id": self.next_id}}
                )
            return httpx.Response(200, json={"ok": True, "result": True})
        if host == "hooks.slack.com" or url.startswith(DISCORD_HOOK) or url.startswith(TEAMS_HOOK):
            return httpx.Response(200, text="ok")
        if host == "slack.com":
            if path.endswith("chat.postMessage"):
                return httpx.Response(200, json={"ok": True, "channel": "D1", "ts": "1.2"})
            return httpx.Response(200, json={"ok": True})
        if host == "discord.com":
            if path.endswith("/users/@me/channels"):
                return httpx.Response(200, json={"id": "DM1"})
            if "/interactions/" in path:
                return httpx.Response(204)
            if request.method == "POST" and path.endswith("/messages"):
                return httpx.Response(200, json={"id": f"M{self.next_id}"})
            return httpx.Response(200, json={})
        if host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "bot-token", "expires_in": 3600})
        if url == "https://login.botframework.com/keys":
            return httpx.Response(200, json=self.jwks)
        if host == "login.botframework.com":
            return httpx.Response(200, json={"jwks_uri": "https://login.botframework.com/keys"})
        if host == "smba.trafficmanager.net":
            return httpx.Response(200, json={"id": f"A{self.next_id}"})
        return httpx.Response(404, json={"error": f"nothing fakes {url}"})

    def to(self, fragment: str) -> list[Sent]:
        return [c for c in self.calls if fragment in c.url]


@pytest.fixture
def chat() -> FakeChat:
    return FakeChat()


@pytest.fixture
def eng(store: JobStore, worktrees_root: Path, seed: Profile, chat: FakeChat) -> Engine:
    provider = full_provider(seed, phases=1)
    engine = full_engine(
        store, worktrees_root, seed, provider, http_transport=httpx.MockTransport(chat)
    )
    engine.update_mail_settings(base_url=BASE)
    return engine


@pytest.fixture
def owner(eng: Engine, store: JobStore) -> Iterator[TestClient]:
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as client:
        _sign_up_owner(client, store)
        yield client


def _owner_id(store: JobStore) -> str:
    user = store.find_by_email("owner@acme.com")
    assert user is not None
    return user.id


def _start(client: TestClient, repo: Path, request: str = "a health check") -> str:
    made = client.post("/api/projects", json={"name": "Note app", "repo_path": str(repo)})
    assert made.status_code == 201, made.text
    started = client.post(f"/api/projects/{made.json()['id']}/jobs", json={"request": request})
    assert started.status_code == 201, started.text
    return str(started.json()["id"])


def _set(client: TestClient, channel: str, **body: Any) -> dict[str, Any]:
    saved = client.put(f"/api/notify/{channel}", json=body)
    assert saved.status_code == 200, saved.text
    return saved.json()  # type: ignore[no-any-return]


def _quiet(eng: Engine, owner_id: str) -> Notifier:
    """A notifier whose decisions do not start the development running in a thread."""
    return Notifier(eng, owner_id, resume=lambda job_id: None)


def _link_telegram(client: TestClient, notifier: Notifier, user_tg_id: int) -> None:
    code = client.post("/api/notify/link-code").json()["code"]
    adapter = notifier.adapter("telegram")
    assert isinstance(adapter, TelegramAdapter)
    handle_update(
        notifier,
        adapter,
        {
            "update_id": 1,
            "message": {
                "chat": {"id": user_tg_id, "type": "private"},
                "from": {"id": user_tg_id, "username": "someone"},
                "text": f"/start {code}",
            },
        },
    )


def _press(notifier: Notifier, user_tg_id: int, data: str) -> None:
    adapter = notifier.adapter("telegram")
    assert isinstance(adapter, TelegramAdapter)
    handle_update(
        notifier,
        adapter,
        {
            "update_id": 2,
            "callback_query": {
                "id": "cb1",
                "data": data,
                "from": {"id": user_tg_id},
                "message": {"chat": {"id": user_tg_id}},
            },
        },
    )


def _asked(chat: FakeChat) -> list[Sent]:
    return [
        c
        for c in chat.to("/sendMessage")
        if isinstance(c.body, dict) and "inline_keyboard" in (c.body.get("reply_markup") or {})
    ]


# -- settings --------------------------------------------------------------------------------


def test_a_stored_bot_token_is_never_read_back(owner: TestClient, chat: FakeChat) -> None:
    view = _set(owner, "telegram", secrets={"token": TG_TOKEN}, fields={"group_chat_id": "-1001"})
    assert view["secrets"]["token"] == {"set": True, "hint": TG_TOKEN[-4:]}
    assert TG_TOKEN not in json.dumps(owner.get("/api/notify").json())
    # the bot's name is asked for once, so the link button can open it
    assert view["bot_name"] == "swbot"
    assert view["group_ready"] and view["bot_ready"]


def test_a_webhook_must_be_https_and_a_token_must_look_like_one(owner: TestClient) -> None:
    plain = owner.put("/api/notify/slack", json={"secrets": {"webhook": "http://hooks.example"}})
    assert plain.status_code == 422
    wrong = owner.put("/api/notify/slack", json={"secrets": {"bot_token": "xapp-1"}})
    assert wrong.status_code == 422
    unknown = owner.put("/api/notify/discord", json={"secrets": {"password": "x"}})
    assert unknown.status_code == 422


def test_a_member_links_their_own_chat_but_does_not_set_the_channels_up(
    eng: Engine, owner: TestClient, store: JobStore
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    _invite(owner, role="architect")
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as member:
        _accept(member, store)
        refused = member.put("/api/notify/telegram", json={"events": ["gate"]})
        assert refused.status_code == 403
        seen = member.get("/api/notify").json()
        assert seen["may_configure"] is False
        telegram = next(c for c in seen["channels"] if c["channel"] == "telegram")
        assert telegram["secrets"] == {} and telegram["bot_ready"] is True
        code = member.post("/api/notify/link-code").json()
        assert code["telegram_url"] == f"https://t.me/swbot?start={code['code']}"


def test_one_accounts_channels_are_not_anothers(eng: Engine, owner: TestClient) -> None:
    _set(owner, "slack", secrets={"webhook": SLACK_HOOK})
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as stranger:
        signed = stranger.post(
            "/api/auth/signup",
            json={"email": "other@else.com", "password": "correct horse", "name": "Bo"},
        )
        assert signed.status_code == 201, signed.text
        slack = next(
            c for c in stranger.get("/api/notify").json()["channels"] if c["channel"] == "slack"
        )
        assert slack["group_ready"] is False


# -- the group -------------------------------------------------------------------------------


def test_every_group_hears_once_that_an_agent_is_waiting(
    eng: Engine, owner: TestClient, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN}, fields={"group_chat_id": "-1001"})
    _set(owner, "slack", secrets={"webhook": SLACK_HOOK})
    _set(owner, "discord", secrets={"webhook": DISCORD_HOOK})
    _set(owner, "teams", secrets={"webhook": TEAMS_HOOK})
    job_id = _start(owner, repo)
    assert eng.store.get(job_id).state is JobState.AWAITING_ARCHITECTURE_APPROVAL

    group = [c for c in chat.to("/sendMessage") if c.body["chat_id"] == "-1001"]
    assert len(group) == 1
    text = group[0].body["text"]
    assert "Note app" in text and "Yazılım Mimarı" in text and "mimari" in text
    assert "a health check" in text and f"{BASE}/projects/" in text
    assert len(chat.to(SLACK_HOOK)) == 1
    assert len(chat.to(DISCORD_HOOK)) == 1
    card = chat.to(TEAMS_HOOK)[0].body["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard" and card["actions"][0]["url"].startswith(BASE)

    # resuming a job that is standing at the gate announces nothing again
    eng.resume(job_id)
    assert len(chat.to(SLACK_HOOK)) == 1


def test_a_group_hears_only_the_events_it_chose(
    eng: Engine, owner: TestClient, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "slack", secrets={"webhook": SLACK_HOOK}, events=["done"])
    job_id = _start(owner, repo)
    assert chat.to(SLACK_HOOK) == []
    owner.post(f"/api/jobs/{job_id}/approve")  # the plan
    owner.post(f"/api/jobs/{job_id}/approve")  # the test cases
    eng.resume(job_id)
    job = eng.store.get(job_id)
    while job.state in (JobState.AWAITING_TEST_APPROVAL, JobState.AWAITING_DEPLOY_APPROVAL):
        job = eng.approve(job_id)
    assert job.state is JobState.DONE, job.state
    posted = chat.to(SLACK_HOOK)
    assert len(posted) == 1 and "tamamlandı" in posted[0].body["text"]


# -- linking and deciding from Telegram --------------------------------------------------------


def test_a_link_code_works_once_and_only_for_this_accounts_bot(
    eng: Engine, owner: TestClient, store: JobStore, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    code = owner.post("/api/notify/link-code").json()["code"]
    assert (
        Notifier(eng, "somebody-else")
        .link("telegram", code=code, external_id="9", address={}, label="")
        .text.startswith("Bu kod geçersiz")
    )
    # the attempt above did not spend it: a code belongs to one bot
    reply = notifier.link(
        "telegram", code=code, external_id="42", address={"chat_id": 42}, label=""
    )
    assert reply.text.startswith("Bağlandı")
    again = notifier.link("telegram", code=code, external_id="43", address={}, label="")
    assert again.text.startswith("Bu kod geçersiz")
    links = owner.get("/api/notify").json()["links"]
    assert [(link["channel"], link["mine"]) for link in links] == [("telegram", True)]


def test_the_owner_is_asked_in_telegram_and_approves_there(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, 42)
    job_id = _start(owner, repo)

    asked = _asked(chat)
    assert len(asked) == 1 and asked[0].body["chat_id"] == 42
    buttons = asked[0].body["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["✓ Devam", "✗ Reddet"]

    _press(notifier, 42, buttons[0]["callback_data"])
    job = eng.store.get(job_id)
    assert job.state is not JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert any("approved by Ada (telegram)" in (t.note or "") for t in job.history)
    edited = chat.to("/editMessageText")[-1].body
    assert "✓ Ada onayladı" in edited["text"] and "reply_markup" not in edited


def test_a_press_from_somebody_elses_account_does_nothing(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, 42)
    job_id = _start(owner, repo)
    data = _asked(chat)[0].body["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    _press(notifier, 666, data)  # the message was forwarded; a stranger presses it
    assert eng.store.get(job_id).state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    answer = chat.to("/answerCallbackQuery")[-1].body["text"]
    assert answer == "Bu soru sana sorulmadı."


def test_rejecting_asks_why_and_the_answer_is_the_feedback(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, 42)
    job_id = _start(owner, repo)
    reject = _asked(chat)[0].body["reply_markup"]["inline_keyboard"][0][1]["callback_data"]

    _press(notifier, 42, reject)
    assert eng.store.get(job_id).state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    why = chat.to("/sendMessage")[-1].body
    assert why["reply_markup"]["force_reply"] is True

    adapter = notifier.adapter("telegram")
    assert isinstance(adapter, TelegramAdapter)
    handle_update(
        notifier,
        adapter,
        {
            "update_id": 3,
            "message": {
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "split the API phase in two",
            },
        },
    )
    job = eng.store.get(job_id)
    assert job.state is not JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert job.history[-1].note == "rejected: split the API phase in two"
    assert "reddetti: split the API phase in two" in chat.to("/editMessageText")[-1].body["text"]


def test_a_button_pressed_after_the_gate_moved_on_is_refused(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, 42)
    job_id = _start(owner, repo)
    approve = _asked(chat)[0].body["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    assert owner.post(f"/api/jobs/{job_id}/approve").status_code == 200  # on the web page
    moved = eng.store.get(job_id)
    assert moved.state is JobState.AWAITING_TEST_APPROVAL
    # the question in the chat was rewritten when the job moved
    assert "karar başka yerde verildi" in chat.to("/editMessageText")[-1].body["text"]

    # and the old button, pressed anyway, does not approve the gate that came next
    _press(notifier, 42, approve)
    assert eng.store.get(job_id).state is JobState.AWAITING_TEST_APPROVAL


def test_a_member_is_asked_only_at_their_own_agents_gate(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    _invite(owner, role="architect")
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as member:
        _accept(member, store)
        notifier = _quiet(eng, _owner_id(store))
        _link_telegram(member, notifier, 77)
        job_id = _start(owner, repo)
        assert [c.body["chat_id"] for c in _asked(chat)] == [77]

        owner.post(f"/api/jobs/{job_id}/approve")
        assert eng.store.get(job_id).state is JobState.AWAITING_TEST_APPROVAL
        assert len(_asked(chat)) == 1  # QA's gate is not the Architect's


def test_a_member_taken_off_the_agent_can_no_longer_decide(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    membership = _invite(owner, role="architect")
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as member:
        _accept(member, store)
        notifier = _quiet(eng, _owner_id(store))
        _link_telegram(member, notifier, 77)
        job_id = _start(owner, repo)
        approve = _asked(chat)[0].body["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        removed = owner.delete(f"/api/agents/architect/members/{membership['id']}")
        assert removed.status_code in (200, 204), removed.text

        _press(notifier, 77, approve)
        assert eng.store.get(job_id).state is JobState.AWAITING_ARCHITECTURE_APPROVAL
        assert (
            chat.to("/answerCallbackQuery")[-1].body["text"] == "Bu kapıda karar verme yetkin yok."
        )


def test_group_chat_id_is_one_command_away(eng: Engine, store: JobStore, chat: FakeChat) -> None:
    notifier = _quiet(eng, None)
    adapter = TelegramAdapter(TG_TOKEN, "", notifier.http)
    handle_update(
        notifier,
        adapter,
        {
            "update_id": 5,
            "message": {"chat": {"id": -1009, "type": "group"}, "text": "/chatid@swbot"},
        },
    )
    assert chat.to("/sendMessage")[-1].body["text"] == "Bu sohbetin kimliği: -1009"


# -- Slack -----------------------------------------------------------------------------------


def test_slack_asks_with_buttons_and_takes_the_reason_from_a_modal(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "slack", secrets={"bot_token": "xoxb-1", "app_token": "xapp-1"})
    notifier = _quiet(eng, _owner_id(store))
    adapter = notifier.adapter("slack")
    assert isinstance(adapter, SlackAdapter)
    code = owner.post("/api/notify/link-code").json()["code"]
    handle_envelope(
        notifier,
        adapter,
        {
            "type": "events_api",
            "payload": {
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "user": "U1",
                    "channel": "D1",
                    "text": f"link {code}",
                }
            },
        },
    )
    assert "Bağlandı" in chat.to("chat.postMessage")[-1].body["text"]

    job_id = _start(owner, repo)
    asked = chat.to("chat.postMessage")[-1].body
    actions = asked["blocks"][1]["elements"]
    prompt_id = actions[1]["value"]

    press = {
        "type": "interactive",
        "payload": {
            "type": "block_actions",
            "user": {"id": "U1"},
            "trigger_id": "T1",
            "actions": [{"action_id": "sw_reject", "value": prompt_id}],
        },
    }
    handle_envelope(notifier, adapter, press)
    assert chat.to("views.open")[-1].body["view"]["private_metadata"] == prompt_id

    empty = {
        "type": "interactive",
        "payload": {
            "type": "view_submission",
            "user": {"id": "U1"},
            "view": {
                "callback_id": REJECT_VIEW,
                "private_metadata": prompt_id,
                "state": {"values": {"reason": {"reason": {"value": "  "}}}},
            },
        },
    }
    kept_open = handle_envelope(notifier, adapter, empty)
    assert kept_open is not None and kept_open["response_action"] == "errors"

    empty["payload"]["view"]["state"]["values"]["reason"]["reason"]["value"] = "use SQLite"
    assert handle_envelope(notifier, adapter, empty) is None
    assert eng.store.get(job_id).history[-1].note == "rejected: use SQLite"
    assert chat.to("chat.update")[-1].body["ts"] == "1.2"


# -- Discord ---------------------------------------------------------------------------------


def test_discord_asks_in_a_direct_message_and_a_button_decides(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "discord", secrets={"bot_token": "x" * 40})
    notifier = _quiet(eng, _owner_id(store))
    adapter = notifier.adapter("discord")
    assert isinstance(adapter, DiscordAdapter)
    code = owner.post("/api/notify/link-code").json()["code"]
    handle_dispatch(
        notifier,
        adapter,
        "MESSAGE_CREATE",
        {"author": {"id": "U9", "username": "ada"}, "channel_id": "DM1", "content": code},
    )

    job_id = _start(owner, repo)
    asked = [c for c in chat.to("/channels/DM1/messages") if c.method == "POST"][-1].body
    custom = asked["components"][0]["components"][0]["custom_id"]
    assert custom.startswith("sw:a:")

    handle_dispatch(
        notifier,
        adapter,
        "INTERACTION_CREATE",
        {
            "id": "I1",
            "token": "tok",
            "type": 3,
            "user": {"id": "U9"},
            "data": {"custom_id": custom},
        },
    )
    assert eng.store.get(job_id).state is not JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert chat.to("/interactions/I1/tok/callback")[-1].body == {"type": 6}
    patched = [c for c in chat.calls if c.method == "PATCH"][-1].body
    assert patched["components"] == [] and "onayladı" in patched["content"]


# -- Teams -----------------------------------------------------------------------------------


def _signed(key: rsa.RSAPrivateKey, claims: dict[str, Any]) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    head = b64(json.dumps({"alg": "RS256", "kid": "k1", "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    signature = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64(signature)}"


@pytest.fixture
def microsoft(chat: FakeChat) -> Iterator[rsa.RSAPrivateKey]:
    """Microsoft's signing key, published where the Bot Framework publishes it."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()

    def b64int(n: int) -> str:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    chat.jwks = {
        "keys": [{"kid": "k1", "kty": "RSA", "n": b64int(numbers.n), "e": b64int(numbers.e)}]
    }
    msteams._keys.update(keys={}, at=0.0)  # nothing cached from another test
    yield key
    msteams._keys.update(keys={}, at=0.0)


def test_teams_believes_only_a_request_microsoft_signed(
    eng: Engine,
    owner: TestClient,
    store: JobStore,
    chat: FakeChat,
    microsoft: rsa.RSAPrivateKey,
) -> None:
    owner_id = _owner_id(store)
    _set(owner, "teams", fields={"app_id": TEAMS_APP}, secrets={"app_password": "s3cret"})
    view = next(c for c in owner.get("/api/notify").json()["channels"] if c["channel"] == "teams")
    assert view["inbound_url"] == f"{BASE}/api/notify/inbound/teams/{owner_id}"
    code = owner.post("/api/notify/link-code").json()["code"]

    activity = {
        "type": "message",
        "serviceUrl": TEAMS_SERVICE,
        "from": {"id": "29:1", "aadObjectId": "aad-1", "name": "Ada"},
        "conversation": {"id": "conv-1"},
        "text": f"link {code}",
    }
    url = f"/api/notify/inbound/teams/{owner_id}"
    now = int(time.time())
    good = {
        "iss": "https://api.botframework.com",
        "aud": TEAMS_APP,
        "exp": now + 600,
        "nbf": now - 10,
        "serviceurl": TEAMS_SERVICE,
    }
    forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as microsoft_calling:  # no session: Microsoft does not log in
        assert microsoft_calling.post(url, json=activity).status_code == 401
        for token in (
            _signed(forged_key, good),  # not Microsoft's key
            _signed(microsoft, {**good, "aud": "someone-else"}),  # another bot's
            _signed(microsoft, {**good, "exp": now - 3600}),  # an old one, replayed
            _signed(microsoft, {**good, "serviceurl": "https://evil.example/"}),
        ):
            refused = microsoft_calling.post(
                url, json=activity, headers={"Authorization": f"Bearer {token}"}
            )
            assert refused.status_code == 401
        assert chat.to("smba.trafficmanager.net") == []  # nothing was acted on

        signed = {"Authorization": f"Bearer {_signed(microsoft, good)}"}
        assert microsoft_calling.post(url, json=activity, headers=signed).status_code == 200
    reply = chat.to("/v3/conversations/conv-1/activities")[-1].body
    assert reply["text"].startswith("Bağlandı")
    assert [link.external_id for link in store.chat_links(owner_id, channel="teams")] == ["aad-1"]


# -- the listeners ---------------------------------------------------------------------------


def test_saving_a_bot_token_starts_its_bot_and_removing_it_stops_it(
    eng: Engine, owner: TestClient, store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from slipwright.notify import listeners as module

    started: list[str] = []

    def idle(engine: Engine, owner_key: str, stop: threading.Event) -> None:
        started.append(owner_key)
        stop.wait(30)

    monkeypatch.setitem(module._LOOPS, "telegram", idle)
    hub = module.Listeners(eng)
    try:
        assert hub.reconcile() == []
        _set(owner, "telegram", secrets={"token": TG_TOKEN})
        assert hub.reconcile() == [f"started telegram for {_owner_id(store)}"]
        assert hub.reconcile() == []  # nothing changed, nothing restarts

        _set(owner, "telegram", secrets={"token": TG_TOKEN.replace("A", "B")})
        assert [line.split()[0] for line in hub.reconcile()] == ["stopped", "started"]

        _set(owner, "telegram", clear=["token"])
        assert hub.reconcile() == [f"stopped telegram for {_owner_id(store)}"]
        assert hub.running() == []
    finally:
        hub.stop_all()


def test_a_database_written_before_notifications_upgrades_into_one(tmp_path: Path) -> None:
    """Built by taking the new shape apart: drop what 0008 adds, stamp the revision before
    it, and let the store upgrade itself the way a server does on start."""
    from alembic import command
    from sqlalchemy import inspect, text

    from slipwright.store.db import Database
    from slipwright.store.migrate import _config, migrate
    from slipwright.store.schema import metadata

    db = Database(str(tmp_path / "old.sqlite3"))
    try:
        metadata.create_all(db.engine)
        with db.begin() as conn:
            for table in ("chat_prompts", "chat_codes", "chat_links"):
                conn.execute(text(f"DROP TABLE {table}"))
            # and what the revisions after it add, since those replay on top (0009)
            for column in ("totp_secret", "totp_enabled_at", "totp_last_step", "totp_recovery"):
                conn.execute(text(f"ALTER TABLE users DROP COLUMN {column}"))
            conn.execute(text("DROP TABLE attachments"))  # (0010)
            conn.execute(text("ALTER TABLE jobs DROP COLUMN title"))  # (0011: job title)
            conn.execute(text("ALTER TABLE job_history DROP COLUMN detail_size"))  # (0014)
            conn.execute(text("DROP TABLE job_messages"))  # (0013)
            for table in ("workers", "worker_codes", "worker_tasks", "worker_calls"):  # (0012)
                conn.execute(text(f"DROP TABLE {table}"))
        command.stamp(_config(db), "0007_teams")

        migrate(db)

        tables = set(inspect(db.engine).get_table_names())
        assert {"chat_links", "chat_codes", "chat_prompts"} <= tables
    finally:
        db.dispose()


# -- a failure, and trying again from the chat -------------------------------------------------


def _fails(eng: Engine, job_id: str, why: str = "mobile_ui failed: provider_rejected") -> None:
    """Stop the development the way a phase that gave up does, and let the engine tell
    whoever it tells."""
    eng.store.update_state(job_id, JobState.FAILED, note=why)
    eng._notify_outcome(eng.store.get(job_id))


def _retried(eng: Engine, job_id: str) -> int:
    return sum(1 for t in eng.store.get(job_id).history if (t.note or "").startswith("retried"))


def test_a_failure_reaches_its_owner_with_a_button_that_tries_again(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, 42)
    job_id = _start(owner, repo)
    _fails(eng, job_id)

    told = _asked(chat)[-1].body
    assert told["chat_id"] == 42
    assert "geliştirme durdu" in told["text"] and "provider_rejected" in told["text"]
    buttons = told["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["↻ Yeniden dene"]

    _press(notifier, 42, buttons[0]["callback_data"])
    assert eng.store.get(job_id).state is not JobState.FAILED
    assert _retried(eng, job_id) == 1
    edited = chat.to("/editMessageText")[-1].body
    assert "↻ Ada yeniden başlattı" in edited["text"] and "reply_markup" not in edited


def test_a_retry_button_pressed_after_the_page_retried_it_does_nothing(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, 42)
    job_id = _start(owner, repo)
    _fails(eng, job_id)
    retry = _asked(chat)[-1].body["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    assert owner.post(f"/api/jobs/{job_id}/retry").status_code == 200  # on the web page
    assert "başka yerden yeniden başlatıldı" in chat.to("/editMessageText")[-1].body["text"]

    _press(notifier, 42, retry)
    assert _retried(eng, job_id) == 1


def test_a_button_from_an_earlier_failure_does_not_retry_a_later_one(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, 42)
    job_id = _start(owner, repo)
    _fails(eng, job_id)
    first = _asked(chat)[-1].body["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    eng.retry(job_id, run=False)
    _fails(eng, job_id, "the same wall again")

    _press(notifier, 42, first)
    assert eng.store.get(job_id).state is JobState.FAILED
    assert _retried(eng, job_id) == 1


def test_only_the_owner_is_offered_a_retry(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    _invite(owner, role="architect")
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as member:
        _accept(member, store)
        notifier = _quiet(eng, _owner_id(store))
        _link_telegram(member, notifier, 77)
        job_id = _start(owner, repo)
        gate = _asked(chat)
        _fails(eng, job_id)
        # moving a stopped development is the owner's; the Architect is not asked
        assert _asked(chat) == gate


def test_a_failure_is_mailed_to_the_owner_when_there_is_a_mail_server(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _start(owner, repo)
    _fails(eng, job_id)
    # no server: the outbox stands in for account letters, not for news
    assert not [m for m in read_outbox(store, to="owner@acme.com") if "durdu" in m["subject"]]

    letters: list[tuple[str, str, str]] = []

    class Recording:
        def send(self, to: str, subject: str, body: str) -> None:
            letters.append((to, subject, body))

    eng.update_mail_settings(transport="smtp", host="smtp.example", from_address="sw@example")
    monkeypatch.setattr(eng, "mailer", lambda: Recording())
    eng.retry(job_id, run=False)
    _fails(eng, job_id)

    assert len(letters) == 1
    to, subject, body = letters[0]
    assert to == "owner@acme.com" and "geliştirme durdu" in subject
    assert "provider_rejected" in body and f"{BASE}/projects/" in body and job_id in body


def test_discord_offers_a_retry_and_its_button_starts_it_again(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "discord", secrets={"bot_token": "x" * 40})
    notifier = _quiet(eng, _owner_id(store))
    adapter = notifier.adapter("discord")
    assert isinstance(adapter, DiscordAdapter)
    code = owner.post("/api/notify/link-code").json()["code"]
    handle_dispatch(
        notifier,
        adapter,
        "MESSAGE_CREATE",
        {"author": {"id": "U9", "username": "ada"}, "channel_id": "DM1", "content": code},
    )
    job_id = _start(owner, repo)
    _fails(eng, job_id)

    told = [c for c in chat.to("/channels/DM1/messages") if c.method == "POST"][-1].body
    buttons = told["components"][0]["components"]
    assert [b["label"] for b in buttons] == ["↻ Yeniden dene"]
    assert buttons[0]["custom_id"].startswith("sw:t:")

    handle_dispatch(
        notifier,
        adapter,
        "INTERACTION_CREATE",
        {
            "id": "I2",
            "token": "tok",
            "type": 3,
            "user": {"id": "U9"},
            "data": {"custom_id": buttons[0]["custom_id"]},
        },
    )
    assert eng.store.get(job_id).state is not JobState.FAILED
    patched = [c for c in chat.calls if c.method == "PATCH"][-1].body
    assert patched["components"] == [] and "yeniden başlattı" in patched["content"]


def test_a_gate_button_forged_onto_a_failure_does_nothing(
    eng: Engine, owner: TestClient, store: JobStore, repo: Path, chat: FakeChat
) -> None:
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, 42)
    job_id = _start(owner, repo)
    _fails(eng, job_id)
    retry = _asked(chat)[-1].body["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    _press(notifier, 42, "a:" + retry.partition(":")[2])
    assert eng.store.get(job_id).state is JobState.FAILED
