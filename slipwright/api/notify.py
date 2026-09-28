"""Notification settings, linking a chat account, and the one door Teams knocks on.

Who may do what:

* **The owner of the account** sets the channels up: the group each service posts to,
  the bot tokens, which events a group hears. These are the account's own settings (the
  ``notify.*`` names are personal in ``store/scoped.py``), so on a hosted installation
  every account brings its own bots and nobody reads another's.
* **Everybody on the account** -- the owner and the people on its agents -- may link their
  own chat account to it and unlink it again. A link is how a question reaches one person,
  and how a press is known to be theirs.
* **Microsoft**, through ``/api/notify/inbound/teams/…``, which is outside the login on
  purpose and proves itself with a signed token instead (``notify/msteams.py``).

A stored secret is never returned: only whether it is set, and its last four characters.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from slipwright.api.auth import current_user, engine_for, require_owner
from slipwright.notify.base import NotifyError
from slipwright.notify.core import CODE_TTL, FIELDS, SECRETS, Notifier
from slipwright.notify.models import CHANNELS, Channel, Event
from slipwright.notify.msteams import TeamsAdapter, handle_activity, verify_token
from slipwright.notify.telegram import TelegramAdapter
from slipwright.schemas.job import utcnow

log = logging.getLogger(__name__)

router = APIRouter(tags=["notifications"])

#: The installation's own account, in a URL: an account id is never empty, so this cannot
#: collide with one.
INSTALLATION_SEGMENT = "_"


class SecretView(BaseModel):
    set: bool
    hint: str | None = None


class ChannelView(BaseModel):
    channel: Channel
    events: list[Event]
    fields: dict[str, str] = Field(
        default_factory=dict, description="The plain settings; empty for a member."
    )
    secrets: dict[str, SecretView] = Field(
        default_factory=dict, description="Which secrets are stored; empty for a member."
    )
    group_ready: bool = Field(description="Whether a group is set up to be told.")
    bot_ready: bool = Field(description="Whether people can link to a bot here.")
    listening: bool = Field(
        description="Whether the bot is connected right now (Teams: whether it is set up)."
    )
    bot_name: str | None = Field(default=None, description="The bot's name, where known.")
    inbound_url: str | None = Field(
        default=None, description="Teams only: the messaging endpoint to give Azure."
    )
    warning: str | None = Field(default=None, description="Set on a save that half worked.")


class LinkView(BaseModel):
    channel: Channel
    user_id: str
    username: str
    label: str
    linked_at: datetime
    mine: bool


class NotifyOverview(BaseModel):
    may_configure: bool
    channels: list[ChannelView]
    links: list[LinkView] = Field(description="The owner sees everyone's; a member their own.")


class ChannelSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[Event] | None = None
    fields: dict[str, str] | None = None
    secrets: dict[str, str] | None = Field(
        default=None, description="New values; a missing or empty one keeps what is stored."
    )
    clear: list[str] = Field(default_factory=list, description="Secrets to remove.")


class LinkCode(BaseModel):
    code: str
    expires_at: datetime
    telegram_url: str | None = Field(
        default=None, description="Opens the bot with the code already in it."
    )


class TestResult(BaseModel):
    sent: list[str]


# -- helpers ---------------------------------------------------------------------------------


def _who(request: Request) -> tuple[str, str, bool]:
    """(whose bots, which person, may they configure). Login off is the installation."""
    user = current_user(request)
    if user.id == "anonymous":
        return "", user.id, True
    return str(user.tenant_id), user.id, not user.is_member


def _notifier(request: Request, owner_key: str) -> Notifier:
    return Notifier(engine_for(request), owner_key or None)


def _listening(request: Request, owner_key: str, channel: str) -> bool:
    listeners = getattr(request.app.state, "notify_listeners", None)
    if listeners is None:
        return False
    return (owner_key, channel) in listeners.running()


def _reconcile(request: Request) -> None:
    listeners = getattr(request.app.state, "notify_listeners", None)
    if listeners is not None:
        listeners.reconcile()


def _hint(value: str) -> str | None:
    return value[-4:] if len(value) >= 8 else None


def _inbound_url(notifier: Notifier, owner_key: str) -> str | None:
    base = (notifier.engine.mail_settings().base_url or "").rstrip("/")
    segment = owner_key or INSTALLATION_SEGMENT
    path = f"/api/notify/inbound/teams/{segment}"
    return f"{base}{path}" if base else path


def _view(request: Request, notifier: Notifier, channel: str, *, full: bool) -> ChannelView:
    cfg = notifier.config(channel)
    adapter = notifier.adapter(channel)
    assert adapter is not None
    bot_name = cfg.fields.get("bot_username") or None
    listening = (
        adapter.has_bot if channel == "teams" else _listening(request, notifier.owner_key, channel)
    )
    return ChannelView(
        channel=channel,
        events=cfg.events,
        fields=dict(cfg.fields) if full else ({"bot_username": bot_name} if bot_name else {}),
        secrets=(
            {k: SecretView(set=bool(v), hint=_hint(v)) for k, v in cfg.secrets.items()}
            if full
            else {}
        ),
        group_ready=adapter.has_group,
        bot_ready=adapter.has_bot,
        listening=listening,
        bot_name=bot_name,
        inbound_url=_inbound_url(notifier, notifier.owner_key)
        if channel == "teams" and full
        else None,
    )


def _username(request: Request, user_id: str) -> str:
    if user_id == "anonymous":
        return "anonymous"
    try:
        return engine_for(request).raw_store.get_user(user_id).username
    except KeyError:
        return user_id


# -- validation ------------------------------------------------------------------------------

_HTTPS = ("https://",)
_SECRET_RULES: dict[tuple[str, str], tuple[re.Pattern[str], str]] = {
    ("telegram", "token"): (
        re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$"),
        "a Telegram bot token looks like 123456:ABC… (from @BotFather)",
    ),
    ("slack", "bot_token"): (re.compile(r"^xoxb-\S+$"), "a Slack bot token starts with xoxb-"),
    ("slack", "app_token"): (
        re.compile(r"^xapp-\S+$"),
        "a Slack app-level token starts with xapp-",
    ),
    ("discord", "bot_token"): (re.compile(r"^\S{20,}$"), "that is not a Discord bot token"),
}
_FIELD_RULES: dict[tuple[str, str], tuple[re.Pattern[str], str]] = {
    ("telegram", "group_chat_id"): (
        re.compile(r"^(-?\d+|@\w{4,})$"),
        "a Telegram group id is a number like -1001234567890 (send /chatid in the group)",
    ),
    ("teams", "app_id"): (
        re.compile(r"^[0-9a-fA-F-]{32,36}$"),
        "a Microsoft app id is a GUID",
    ),
    ("teams", "tenant_id"): (
        re.compile(r"^[0-9a-fA-F-]{32,36}$"),
        "a tenant id is a GUID; leave it empty for a multi-tenant bot",
    ),
}


def _check(channel: str, body: ChannelSettingsIn) -> None:
    for name in body.fields or {}:
        if name not in FIELDS[channel] or name == "bot_username":
            raise HTTPException(status_code=422, detail=f"{channel} has no setting {name!r}")
    for name in [*(body.secrets or {}), *body.clear]:
        if name not in SECRETS[channel]:
            raise HTTPException(status_code=422, detail=f"{channel} has no secret {name!r}")
    for name, value in (body.fields or {}).items():
        rule = _FIELD_RULES.get((channel, name))
        if value.strip() and rule and not rule[0].match(value.strip()):
            raise HTTPException(status_code=422, detail=rule[1])
    for name, value in (body.secrets or {}).items():
        value = value.strip()
        if not value:
            continue
        if name == "webhook" and not value.startswith(_HTTPS):
            raise HTTPException(
                status_code=422, detail="a webhook address must start with https://"
            )
        rule = _SECRET_RULES.get((channel, name))
        if rule and not rule[0].match(value):
            raise HTTPException(status_code=422, detail=rule[1])


# -- endpoints -------------------------------------------------------------------------------


@router.get("/notify", response_model=NotifyOverview)
def get_notify(request: Request) -> NotifyOverview:
    """The channels as this person may see them, and the chat accounts linked here."""
    owner_key, user_id, may_configure = _who(request)
    notifier = _notifier(request, owner_key)
    links = notifier.store.chat_links(owner_key, user_id=None if may_configure else user_id)
    return NotifyOverview(
        may_configure=may_configure,
        channels=[_view(request, notifier, c, full=may_configure) for c in CHANNELS],
        links=[
            LinkView(
                channel=link.channel,
                user_id=link.user_id,
                username=_username(request, link.user_id),
                label=link.label,
                linked_at=link.linked_at,
                mine=link.user_id == user_id,
            )
            for link in links
        ],
    )


@router.put("/notify/{channel}", response_model=ChannelView)
def put_notify(channel: Channel, body: ChannelSettingsIn, request: Request) -> ChannelView:
    require_owner(request)
    owner_key, _, _ = _who(request)
    _check(channel, body)
    notifier = _notifier(request, owner_key)
    store = notifier.engine.store
    data: dict[str, Any] = dict(store.get_setting(f"notify.{channel}", {}) or {})
    if body.events is not None:
        data["events"] = sorted(set(body.events), key=["gate", "failed", "done"].index)
    for name, value in (body.fields or {}).items():
        data[name] = value.strip()
    token_changed = False
    for name, value in (body.secrets or {}).items():
        if value.strip():
            store.set_setting(f"notify.{channel}.{name}", value.strip(), secret=True)
            token_changed = token_changed or name == "token"
    for name in body.clear:
        store.delete_setting(f"notify.{channel}.{name}")
        token_changed = token_changed or name == "token"
    warning: str | None = None
    if channel == "telegram" and token_changed:
        # the bot's @name is what the link button opens; asked once, when the token moves
        data["bot_username"] = ""
        token = str(store.get_setting("notify.telegram.token") or "")
        if token:
            try:
                me = TelegramAdapter(token, "", notifier.http).me()
                data["bot_username"] = str(me.get("username") or "")
            except NotifyError as exc:
                warning = f"saved, but Telegram did not accept the token: {exc}"
    store.set_setting(f"notify.{channel}", data)
    _reconcile(request)
    view = _view(request, Notifier(engine_for(request), owner_key or None), channel, full=True)
    view.warning = warning
    return view


@router.post("/notify/{channel}/test", response_model=TestResult)
def test_notify(channel: Channel, request: Request) -> TestResult:
    """A test message to the group, and to the caller's own linked chat."""
    require_owner(request)
    owner_key, user_id, _ = _who(request)
    try:
        sent = _notifier(request, owner_key).test(channel, user_id=user_id)
    except NotifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestResult(sent=sent)


@router.post("/notify/link-code", response_model=LinkCode)
def link_code(request: Request) -> LinkCode:
    """A one-time code that, sent to one of the account's bots, links that chat account to
    the caller. Asking again replaces the previous code."""
    owner_key, user_id, _ = _who(request)
    notifier = _notifier(request, owner_key)
    code = notifier.new_code(user_id)
    bot = notifier.config("telegram").fields.get("bot_username")
    return LinkCode(
        code=code,
        expires_at=utcnow() + CODE_TTL,
        telegram_url=f"https://t.me/{bot}?start={code}" if bot else None,
    )


@router.delete("/notify/links/{channel}", status_code=204)
def unlink_mine(channel: Channel, request: Request) -> None:
    owner_key, user_id, _ = _who(request)
    engine_for(request).raw_store.delete_chat_link(owner_key, channel, user_id)


@router.delete("/notify/links/{channel}/{user_id}", status_code=204)
def unlink(channel: Channel, user_id: str, request: Request) -> None:
    """The owner taking somebody's chat off the account -- they left, the phone was lost."""
    require_owner(request)
    owner_key, _, _ = _who(request)
    if not engine_for(request).raw_store.delete_chat_link(owner_key, channel, user_id):
        raise HTTPException(status_code=404, detail="no such link")


@router.post("/notify/inbound/teams/{owner}", include_in_schema=False)
def teams_inbound(
    owner: str, request: Request, activity: Annotated[dict[str, Any], Body()]
) -> dict[str, Any]:
    """Microsoft's delivery of one activity to this account's Teams bot. Outside the login:
    the signed token is checked before anything in the body is acted on. Not ``async``:
    the check and the answer are blocking HTTP calls and belong on the thread pool."""
    owner_key = "" if owner == INSTALLATION_SEGMENT else owner
    notifier = Notifier(engine_for(request), owner_key or None)
    adapter = notifier.adapter("teams")
    if not isinstance(adapter, TeamsAdapter) or not adapter.has_bot:
        raise HTTPException(status_code=404, detail="no Teams bot here")
    try:
        verify_token(
            request.headers.get("authorization"),
            app_id=adapter.app_id,
            service_url=str(activity.get("serviceUrl") or ""),
            http=notifier.http,
        )
    except NotifyError as exc:
        log.warning("teams inbound for %s refused: %s", owner_key or "installation", exc)
        raise HTTPException(status_code=401, detail="unauthorised") from exc
    try:
        handle_activity(notifier, adapter, activity)
    except NotifyError as exc:
        log.warning("teams inbound: could not answer: %s", exc)
    return {}


__all__ = ["router"]
