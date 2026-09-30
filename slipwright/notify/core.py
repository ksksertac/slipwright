"""The notifier: who is told what, and what a press in a chat is allowed to do.

Everything that decides lives here; the channel modules only speak their service's
protocol. Three rules hold it up:

* **A press is believed only through a link.** The chat service tells us which of *its*
  users pressed. That id must be linked -- by a one-time code the person copied out of
  Slipwright -- to exactly the person the question was put to, or nothing happens.
* **A press does what the web page's button would, under the same guard.** The owner may
  decide at every gate of their own developments, a member only at their agent's, nobody
  on the worked example. That is ``_refusal``, the chat twin of the API's ``_may_act``.
* **A question is about one gate visit.** The prompt carries the visit's marker; a
  button pressed after the gate has moved on -- approved on the web page, rejected by a
  colleague, the development re-planned -- is told so and does nothing. Otherwise an old
  message could approve a gate its reader has never seen.

A failure is asked about the same way: its owner gets "try again?" in their own chat,
the prompt carries which failure it was, and a press after the development has already
been retried from the page -- or has failed again since -- does nothing.

Nothing here may stop a development: every call out is caught and logged.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import httpx

from slipwright.notify.ask import ask
from slipwright.notify.base import Adapter, NotifyError
from slipwright.notify.discord import DiscordAdapter
from slipwright.notify.models import CHANNELS, EVENTS, ChatLink, ChatPrompt
from slipwright.notify.msteams import TeamsAdapter
from slipwright.notify.slack import SlackAdapter
from slipwright.notify.telegram import TelegramAdapter
from slipwright.notify.text import (
    Message,
    builder_message,
    gate_message,
    outcome_message,
    test_message,
    word,
)
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState, utcnow
from slipwright.teams import agent_for_gate, may_act_at

if TYPE_CHECKING:
    from slipwright.engine import Engine

log = logging.getLogger(__name__)

#: How long a link code works. Long enough to switch to the phone and find the bot.
CODE_TTL = timedelta(minutes=30)

#: The secrets each channel keeps, by setting name. Read back only as "set or not".
SECRETS: dict[str, tuple[str, ...]] = {
    "telegram": ("token",),
    "slack": ("webhook", "bot_token", "app_token"),
    "discord": ("webhook", "bot_token"),
    "teams": ("webhook", "app_password"),
}
#: The plain fields each channel keeps beside its secrets.
FIELDS: dict[str, tuple[str, ...]] = {
    "telegram": ("group_chat_id", "bot_username"),
    "slack": (),
    "discord": (),
    "teams": ("app_id", "tenant_id"),
}
#: What a group is told when nobody has chosen: the gates, which are what somebody has to
#: act on. Failures and finishes are one click away.
DEFAULT_EVENTS = ["gate", "failed", "cancelled"]


def gate_marker(job: Job) -> str:
    """Which visit to which gate the job is at: ``awaiting_architecture_approval:2``.
    Empty when it is not waiting. The same marker the team mail is deduplicated on."""
    if job.state not in APPROVAL_STATES:
        return ""
    visits = sum(
        1 for t in job.history if t.to_state is job.state and t.from_state is not job.state
    )
    return f"{job.state.value}:{visits}"


def failure_marker(job: Job) -> str:
    """Which failure a stopped job is at: ``failed:2`` the second time it failed. Empty
    when it has not. What a "try again" button is tied to, as a gate's is to its visit."""
    if job.state is not JobState.FAILED:
        return ""
    visits = sum(
        1 for t in job.history if t.to_state is job.state and t.from_state is not job.state
    )
    return f"{job.state.value}:{visits}"


def current_marker(job: Job) -> str:
    """What a question about this job must be about to still be answerable."""
    return gate_marker(job) or failure_marker(job)


@dataclass
class ChannelConfig:
    channel: str
    events: list[str] = field(default_factory=lambda: list(DEFAULT_EVENTS))
    fields: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> str:
        return self.fields.get(name) or self.secrets.get(name) or ""


@dataclass
class Reply:
    """What a press or a message comes to, for the channel to show."""

    text: str
    #: set when the question is settled; the message has already been rewritten to it
    final: str | None = None
    #: the person pressed "reject" and must say why before anything happens
    ask_reason: bool = False
    #: (label, callback data) pairs to put under the message. A question the bot asks of
    #: its own accord -- "shall I start this?" -- rather than a gate, which has its own
    #: prompt rows and its own buttons.
    buttons: list[tuple[str, str]] = field(default_factory=list)


def _default_resume(engine: Engine) -> Callable[[str], None]:
    def resume(job_id: str) -> None:
        def run() -> None:
            try:
                engine.resume(job_id)
            except Exception:  # noqa: BLE001 - a background thread has nobody to raise to
                log.exception("job %s: run after a chat decision failed", job_id)

        threading.Thread(target=run, daemon=True).start()

    return resume


class Notifier:
    """One account's notifications. ``owner_id`` ``None`` is the installation's own."""

    def __init__(
        self,
        engine: Engine,
        owner_id: str | None,
        *,
        lang: str = "tr",
        resume: Callable[[str], None] | None = None,
    ) -> None:
        self.owner_key = owner_id or ""
        # settings are read as this account; jobs and links through the raw store,
        # filtered by owner explicitly where it matters
        self.engine = engine.for_user(owner_id)
        self.store = engine.raw_store
        self.lang = lang
        self.resume = resume or _default_resume(self.engine)
        self._adapters: dict[str, Adapter | None] = {}

    # -- configuration ---------------------------------------------------------------------

    def config(self, channel: str) -> ChannelConfig:
        settings = self.engine.store
        data: dict[str, Any] = settings.get_setting(f"notify.{channel}", {}) or {}
        events = data.get("events")
        return ChannelConfig(
            channel=channel,
            events=[e for e in events if e in EVENTS]
            if isinstance(events, list)
            else list(DEFAULT_EVENTS),
            fields={k: str(data.get(k) or "") for k in FIELDS[channel]},
            secrets={
                k: str(settings.get_setting(f"notify.{channel}.{k}") or "")
                for k in SECRETS[channel]
            },
        )

    def http(self) -> httpx.Client:
        return httpx.Client(transport=self.engine.http_transport)

    def adapter(self, channel: str) -> Adapter | None:
        if channel in self._adapters:
            return self._adapters[channel]
        cfg = self.config(channel)
        found: Adapter | None
        if channel == "telegram":
            found = TelegramAdapter(
                cfg.get("token"), cfg.get("group_chat_id"), self.http, self.lang
            )
        elif channel == "slack":
            found = SlackAdapter(
                cfg.get("webhook"), cfg.get("bot_token"), cfg.get("app_token"), self.http, self.lang
            )
        elif channel == "discord":
            found = DiscordAdapter(cfg.get("webhook"), cfg.get("bot_token"), self.http, self.lang)
        elif channel == "teams":
            found = TeamsAdapter(
                cfg.get("webhook"),
                cfg.get("app_id"),
                cfg.get("app_password"),
                cfg.get("tenant_id"),
                self.http,
                self.lang,
            )
        else:
            found = None
        self._adapters[channel] = found
        return found

    # -- what a message links to ---------------------------------------------------------------

    def _link(self, job: Job) -> str | None:
        base = (self.engine.mail_settings().base_url or "").rstrip("/")
        if not base:
            return None  # a relative link in a chat goes nowhere
        if job.project_id:
            return f"{base}/projects/{job.project_id}/jobs/{job.id}"
        return base

    def _project(self, job: Job) -> str:
        if not job.project_id:
            return ""
        try:
            return self.store.get_project(job.project_id).name
        except Exception:  # noqa: BLE001 - a deleted project still has a job to report
            return ""

    # -- out: the group ---------------------------------------------------------------------

    def announce(self, job: Job, kind: str, *, error: str | None = None) -> list[str]:
        """Tell every group that asked for this kind of event. Returns where it went."""
        if kind == "builder":
            msg = builder_message(
                job, project=self._project(job), link=self._link(job), lang=self.lang
            )
            kind = "gate"  # heard by the groups that hear of gates: it waits on a person too
        elif kind == "gate":
            msg = gate_message(
                job,
                role=agent_for_gate(job.state),
                project=self._project(job),
                link=self._link(job),
                lang=self.lang,
            )
        else:
            msg = outcome_message(
                job,
                kind,
                project=self._project(job),
                link=self._link(job),
                lang=self.lang,
                error=error,
            )
        told: list[str] = []
        for channel in CHANNELS:
            adapter = self.adapter(channel)
            if adapter is None or not adapter.has_group:
                continue
            if kind not in self.config(channel).events:
                continue
            try:
                adapter.post_group(msg)
                told.append(channel)
            except NotifyError as exc:
                log.warning("job %s: %s group not told: %s", job.id, channel, exc)
        return told

    def test(self, channel: str, *, user_id: str | None = None) -> list[str]:
        """Send the test message wherever this channel is set up. Raises what went wrong."""
        adapter = self.adapter(channel)
        if adapter is None:
            raise NotifyError(f"unknown channel {channel}")
        msg = test_message(self.lang)
        sent: list[str] = []
        if adapter.has_group:
            adapter.post_group(msg)
            sent.append("group")
        if adapter.has_bot and user_id is not None:
            for link in self.store.chat_links(self.owner_key, channel=channel, user_id=user_id):
                adapter.say(link.address, msg.text())
                sent.append("direct")
        if not sent:
            raise NotifyError("nothing to send to: set a group or link your own account first")
        return sent

    # -- out: the people ---------------------------------------------------------------------

    def _is_recipient(self, user_id: str, job: Job) -> bool:
        """Whether this linked person is somebody the gate is waiting for."""
        if not self.owner_key or user_id == job.owner_id:
            return True
        role = agent_for_gate(job.state)
        if role is None:
            return False
        try:
            user = self.store.get_user(user_id)
        except KeyError:
            return False
        return user.tenant_id == self.owner_key and role in self.store.agents_of(user_id)

    def ask(self, job: Job) -> list[ChatPrompt]:
        """Put the gate to everybody linked who may decide it, each in their own chat."""
        marker = gate_marker(job)
        if not marker:
            return []
        msg: Message | None = None
        asked: list[ChatPrompt] = []
        for link in self.store.chat_links(self.owner_key):
            adapter = self.adapter(link.channel)
            if adapter is None or not adapter.has_bot or not self._is_recipient(link.user_id, job):
                continue
            if msg is None:
                msg = gate_message(
                    job,
                    role=agent_for_gate(job.state),
                    project=self._project(job),
                    link=self._link(job),
                    lang=self.lang,
                )
            prompt = self.store.add_chat_prompt(
                owner_id=self.owner_key,
                user_id=link.user_id,
                channel=link.channel,
                external_id=link.external_id,
                job_id=job.id,
                marker=marker,
                address=link.address,
            )
            try:
                ref = adapter.ask(link.address, msg, prompt.id)
            except NotifyError as exc:
                log.warning(
                    "job %s: could not ask %s on %s: %s", job.id, link.label, link.channel, exc
                )
                self.store.set_chat_prompt(prompt.id, status="closed")
                continue
            self.store.set_chat_prompt(prompt.id, ref=ref)
            asked.append(prompt)
        return asked

    def offer_retry(self, job: Job, *, error: str | None = None) -> list[ChatPrompt]:
        """Tell the owner, in their own chat, that the development stopped, with a button
        to try it again. Only the owner: retrying is theirs, never a member's (``_refusal``
        says the same when the button is pressed). The worked example is never offered --
        it has nothing to run."""
        marker = failure_marker(job)
        if not marker or self._is_demo(job):
            return []
        msg: Message | None = None
        asked: list[ChatPrompt] = []
        for link in self.store.chat_links(self.owner_key):
            adapter = self.adapter(link.channel)
            if adapter is None or not adapter.has_bot:
                continue
            if self.owner_key and link.user_id != job.owner_id:
                continue
            if msg is None:
                msg = outcome_message(
                    job,
                    "failed",
                    project=self._project(job),
                    link=self._link(job),
                    lang=self.lang,
                    error=error,
                )
            prompt = self.store.add_chat_prompt(
                owner_id=self.owner_key,
                user_id=link.user_id,
                channel=link.channel,
                external_id=link.external_id,
                job_id=job.id,
                marker=marker,
                address=link.address,
            )
            try:
                # a message of kind "failed" is asked with one button: try again
                ref = adapter.ask(link.address, msg, prompt.id)
            except NotifyError as exc:
                log.warning(
                    "job %s: could not offer a retry to %s on %s: %s",
                    job.id,
                    link.label,
                    link.channel,
                    exc,
                )
                self.store.set_chat_prompt(prompt.id, status="closed")
                continue
            self.store.set_chat_prompt(prompt.id, ref=ref)
            asked.append(prompt)
        return asked

    def _stale(self, prompt: ChatPrompt) -> str:
        """What an unanswerable question comes to: a gate decided elsewhere, or a failure
        that is no longer the one the question was about."""
        if prompt.marker.startswith(f"{JobState.FAILED.value}:"):
            return word(self.lang, "moved_on")
        return word(self.lang, "decided_elsewhere")

    def settle(self, job: Job) -> int:
        """Close every question about a gate visit -- or a failure -- this job is no longer
        at. Called when the job moves, whoever moved it: the web page, the API, a chat."""
        marker = current_marker(job)
        closed = 0
        for prompt in self.store.open_chat_prompts(job.id):
            if prompt.marker == marker:
                continue
            self._finish(prompt, self._stale(prompt), status="closed")
            closed += 1
        return closed

    def _finish(self, prompt: ChatPrompt, outcome: str, *, status: str | None) -> None:
        if status is not None:
            self.store.set_chat_prompt(prompt.id, status=status)
        adapter = self.adapter(prompt.channel)
        if adapter is None or not adapter.has_bot:
            return
        try:
            adapter.settle(prompt.address, prompt.ref, outcome)
        except NotifyError as exc:
            log.info("prompt %s: could not rewrite the message: %s", prompt.id, exc)

    # -- linking ------------------------------------------------------------------------------

    def new_code(self, user_id: str) -> str:
        return self.store.create_chat_code(self.owner_key, user_id, ttl=CODE_TTL)

    def link(
        self, channel: str, *, code: str, external_id: str, address: dict[str, Any], label: str
    ) -> Reply:
        user_id = self.store.redeem_chat_code(self.owner_key, code)
        if user_id is None or not external_id:
            return Reply(word(self.lang, "bad_code"))
        from slipwright.store.chat import new_link_id

        self.store.save_chat_link(
            ChatLink(
                id=new_link_id(),
                owner_id=self.owner_key,
                user_id=user_id,
                channel=channel,
                external_id=external_id,
                address=address,
                label=label,
                linked_at=utcnow(),
            )
        )
        name = label or external_id
        with contextlib.suppress(KeyError):
            name = self.store.get_user(user_id).username
        log.info("%s account %s linked to %s", channel, external_id, user_id)
        return Reply(word(self.lang, "linked", name=name))

    # -- in -------------------------------------------------------------------------------

    def on_text(
        self, channel: str, *, external_id: str, address: dict[str, Any], label: str, text: str
    ) -> Reply | None:
        """Something typed to the bot: a link code, the reason for a rejection, or a
        question about where things stand (``notify/ask.py``)."""
        text = text.strip()
        if not text:
            return None
        head, _, rest = text.partition(" ")
        if head.lower().lstrip("/") in ("start", "link", "bagla", "bağla") and rest.strip():
            return self.link(
                channel, code=rest.strip(), external_id=external_id, address=address, label=label
            )
        waiting = self.store.chat_prompt_awaiting_reason(self.owner_key, channel, external_id)
        if waiting is not None:
            return self.on_press(
                channel, external_id=external_id, prompt_id=waiting.id, action="reject", reason=text
            )
        compact = text.replace("-", "").replace(" ", "")
        if len(compact) == 8 and compact.isalnum():
            return self.link(
                channel, code=compact, external_id=external_id, address=address, label=label
            )
        link = self.store.chat_link_for(self.owner_key, channel, external_id)
        if link is None:
            return Reply(word(self.lang, "hello"))
        # a linked person asking where things stand. Answered from the store, as them,
        # and never by letting a model near the database -- see notify/ask.py
        answer = ask(self, user_id=link.user_id, text=text)
        if answer is None:
            return None
        return Reply(answer.text, buttons=answer.buttons)

    def _is_demo(self, job: Job) -> bool:
        if not job.project_id:
            return False
        try:
            return bool(self.store.get_project(job.project_id).is_demo)
        except Exception:  # noqa: BLE001 - a missing project has no demo flag
            return False

    def _refusal(self, user_id: str, job: Job) -> str | None:
        """Why this person may not decide at this job's gate, or ``None``. The chat twin of
        the API's ``_may_act`` -- and, for a failed job, of ``require_owner`` on the retry
        endpoint: moving a stopped development is the owner's alone."""
        if self._is_demo(job):
            return word(self.lang, "demo")
        if not self.owner_key or user_id == job.owner_id:
            return None
        if job.state is JobState.FAILED:
            return word(self.lang, "owner_only")
        try:
            user = self.store.get_user(user_id)
        except KeyError:
            return word(self.lang, "not_allowed")
        if user.tenant_id != job.owner_id:
            return word(self.lang, "not_allowed")
        if not may_act_at(user, job, self.store.agents_of(user_id)):
            return word(self.lang, "not_allowed")
        return None

    def on_press(
        self,
        channel: str,
        *,
        external_id: str,
        prompt_id: str,
        action: str,
        reason: str | None = None,
    ) -> Reply:
        prompt = self.store.get_chat_prompt(prompt_id)
        if (
            prompt is None
            or prompt.owner_id != self.owner_key
            or prompt.channel != channel
            or prompt.external_id != external_id
        ):
            return Reply(word(self.lang, "not_yours"))
        link = self.store.chat_link_for(self.owner_key, channel, external_id)
        if link is None or link.user_id != prompt.user_id:
            return Reply(word(self.lang, "not_linked"))
        if prompt.answered:
            return Reply(self._stale(prompt))
        try:
            job = self.store.get(prompt.job_id)
        except KeyError:
            self._finish(prompt, self._stale(prompt), status="closed")
            return Reply(self._stale(prompt))
        if current_marker(job) != prompt.marker:
            self.settle(job)
            return Reply(self._stale(prompt))
        refused = self._refusal(link.user_id, job)
        if refused is not None:
            return Reply(refused)
        # each question offers its own buttons: a failure only "try again", a gate only
        # "carry on" and "reject". Anything else arriving is a forged press
        if job.state is JobState.FAILED:
            if action != "retry":
                return Reply(word(self.lang, "not_yours"))
            return self._retry(prompt, job, link, external_id)
        if action not in ("approve", "reject"):
            return Reply(word(self.lang, "not_yours"))

        reason = (reason or "").strip() or None
        if action == "reject" and reason is None:
            self.store.claim_chat_prompt(prompt.id, ("open", "reason"), "reason")
            return Reply(word(self.lang, "why"), ask_reason=True)
        status = "approved" if action == "approve" else "rejected"
        if not self.store.claim_chat_prompt(prompt.id, ("open", "reason"), status):
            return Reply(word(self.lang, "decided_elsewhere"))

        name = link.label or external_id
        with contextlib.suppress(KeyError):
            name = self.store.get_user(link.user_id).username
        from slipwright.engine import EmptyApproval, NotAwaitingApproval

        engine = self.engine
        try:
            if status == "approved":
                engine.approve(job.id, run=False, by=f"{name} ({channel})")
                outcome = word(self.lang, "approved_by", name=name)
            else:
                engine.reject(job.id, reason or "", run=False)
                outcome = word(self.lang, "rejected_by", name=name, reason=reason)
        except NotAwaitingApproval:
            self._finish(prompt, word(self.lang, "decided_elsewhere"), status="closed")
            return Reply(word(self.lang, "decided_elsewhere"))
        except EmptyApproval as exc:
            self.store.set_chat_prompt(prompt.id, status="open")
            return Reply(word(self.lang, "failed", error=str(exc)))
        # everybody who was asked about this visit sees how it ended, the presser too
        self._finish(prompt, outcome, status=None)
        for other in self.store.open_chat_prompts(job.id):
            if other.marker == prompt.marker:
                self._finish(other, outcome, status="closed")
        self.resume(job.id)
        return Reply(outcome, final=outcome)

    def _retry(self, prompt: ChatPrompt, job: Job, link: ChatLink, external_id: str) -> Reply:
        """The "try again" button: what the page's Retry does, on the owner's word."""
        if not self.store.claim_chat_prompt(prompt.id, ("open",), "retried"):
            return Reply(self._stale(prompt))
        name = link.label or external_id
        with contextlib.suppress(KeyError):
            name = self.store.get_user(link.user_id).username
        from slipwright.engine import NotAwaitingApproval

        try:
            self.engine.retry(job.id, run=False)
        except NotAwaitingApproval:
            self._finish(prompt, self._stale(prompt), status="closed")
            return Reply(self._stale(prompt))
        except Exception as exc:  # noqa: BLE001 - whatever it was, it is the presser's answer
            log.warning("job %s: retry from %s failed: %r", job.id, prompt.channel, exc)
            self.store.set_chat_prompt(prompt.id, status="open")
            return Reply(word(self.lang, "failed", error=str(exc)))
        outcome = word(self.lang, "retried_by", name=name)
        self._finish(prompt, outcome, status=None)
        for other in self.store.open_chat_prompts(job.id):
            if other.marker == prompt.marker:
                self._finish(other, outcome, status="closed")
        self.resume(job.id)
        return Reply(outcome, final=outcome)


def notify_gate(engine: Engine, job: Job) -> None:
    """The engine's one call when a job arrives at a gate. Never raises."""
    try:
        notifier = Notifier(engine, job.owner_id)
        notifier.announce(job, "gate")
        notifier.ask(job)
    except Exception:  # noqa: BLE001 - a gate must never wait on a chat service
        log.exception("job %s: chat notification failed", job.id)


def notify_builder_wait(engine: Engine, job: Job) -> None:
    """A development waits for a machine that can build its apps. Only the groups hear of
    it: there is no button to press in anyone's own chat. Never raises."""
    try:
        Notifier(engine, job.owner_id).announce(job, "builder")
    except Exception:  # noqa: BLE001 - a wait must never wait on a chat service
        log.exception("job %s: chat notification failed", job.id)


def notify_outcome(engine: Engine, job: Job, kind: str, error: str | None = None) -> None:
    """The groups hear of every outcome they asked for; a failure is also put to its owner
    in their own chat, with a button to try again."""
    try:
        notifier = Notifier(engine, job.owner_id)
        notifier.announce(job, kind, error=error)
        if kind == "failed":
            notifier.offer_retry(job, error=error)
    except Exception:  # noqa: BLE001
        log.exception("job %s: chat notification failed", job.id)


def settle_prompts(engine: Engine, job: Job) -> None:
    try:
        if engine.raw_store.open_chat_prompts(job.id):
            Notifier(engine, job.owner_id).settle(job)
    except Exception:  # noqa: BLE001
        log.exception("job %s: could not settle chat questions", job.id)


__all__ = [
    "CODE_TTL",
    "DEFAULT_EVENTS",
    "FIELDS",
    "SECRETS",
    "ChannelConfig",
    "Notifier",
    "Reply",
    "current_marker",
    "failure_marker",
    "gate_marker",
    "notify_builder_wait",
    "notify_gate",
    "notify_outcome",
    "settle_prompts",
]
