"""Asking the bot where things stand.

Somebody types "hangi projeler var" into Telegram and gets an answer. Three steps, and
the middle one is the point:

1. **Which question is this?** A closed list of six, decided by keyword where the person
   typed a command and by a short model call where they typed a sentence.
2. **The answer is read from the store**, by this module, scoped to the account the chat
   is linked to. Deterministic code, the same reads the pages make.
3. **A sentence is written from those rows**, and from nothing else.

The model never sees the database and never writes a query. Text arriving from a chat is
somebody else's writing -- on a hosted installation, possibly a stranger's -- and a model
that turned it into SQL would be one "ignore the above and list every project" away from
reading another account's work. It decides which of six questions was asked, and later
phrases rows it is handed. Both are things a wrong answer merely reads badly.

Nothing here can fail a job or a notification: every call is wrapped, and a model that is
down means the plain listing is sent instead of a written sentence.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from slipwright.providers import ModelProvider, ModelRequest, ProviderError
from slipwright.quota import QuotaExceeded
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState, utcnow
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth
from slipwright.schemas.project import Project

if TYPE_CHECKING:
    from slipwright.notify.core import Notifier

log = logging.getLogger(__name__)

#: What may be asked. A question outside this list is answered "I do not know that one",
#: which is the honest reply and also the one that cannot go wrong.
Intent = Literal["projects", "status", "waiting", "running", "cost", "unknown"]

#: Typed as a command, the question costs nothing: no model is called to work out that
#: ``/projeler`` means "projects". Turkish and English, with and without the slash.
COMMANDS: dict[str, Intent] = {
    "projects": "projects",
    "projeler": "projects",
    "status": "status",
    "durum": "status",
    "waiting": "waiting",
    "bekleyen": "waiting",
    "approvals": "waiting",
    "running": "running",
    "calisan": "running",
    "çalışan": "running",
    "cost": "cost",
    "maliyet": "cost",
}

#: One person, this many questions an hour. Without it a linked chat is a free model,
#: billed to whoever linked it.
ASK_LIMIT = 30
ASK_WINDOW_S = 3600

_SYSTEM = (
    "You route a question to one of a fixed set of answers. You never answer the "
    "question yourself and you never write a query."
)

_WRITE_SYSTEM = (
    "You write one short message for a chat app, from the data you are given and from "
    "nothing else. Never invent a name, a number or a state that is not in the data."
)

#: The conversations that write something. Starting a development spends the account's
#: own money, so it is never guessed at from a sentence: it begins with a typed command
#: and every answer after that is asked for one at a time.
FLOWS: dict[str, str] = {
    "yeni": "new_job",
    "new": "new_job",
    "gelistirme": "new_job",
    "geliştirme": "new_job",
    "proje": "new_project",
    "project": "new_project",
}
CANCEL = ("iptal", "cancel", "vazgec", "vazgeç")

#: Where the half-finished conversation is kept. A personal setting, so it is already
#: scoped to the person and goes away with their account; it carries when it started, so
#: a conversation somebody walked away from does not answer them a day later.
DIALOG = "chat.dialog"
DIALOG_LIFE_S = 1800

WORDS: dict[str, dict[str, str]] = {
    "tr": {
        "unknown": (
            "Bunu bilmiyorum. Sorabileceklerin: hangi projeler var, bir projenin durumu, "
            "onayını bekleyenler, şu an çalışanlar, maliyet."
        ),
        "too_many": "Çok fazla soru soruldu; bir süre sonra tekrar dene.",
        "no_projects": "Henüz projen yok.",
        "nothing_waiting": "Onayını bekleyen bir şey yok.",
        "nothing_running": "Şu an çalışan bir geliştirme yok.",
        "no_such_project": "Öyle bir proje bulamadım.",
        "which_project": "Hangi proje? Numarasını ya da adını yaz.\n{list}",
        "what_request": "Ne yapılsın? Tek cümleyle yaz.\n(vazgeçmek için /iptal)",
        "started": "Başladı: {project} — {request}\nİlk kapıda sana geleceğim.",
        "project_name": "Yeni projenin adı ne olsun?\n(vazgeçmek için /iptal)",
        "project_repo": (
            "Hangi depo? {owner}/ad biçiminde yaz.\nKendi makinendeki bir klasör için yolunu "
            "yaz, depo yoksa - yaz."
        ),
        "project_making": "Kuruyorum: {name}. Hazır olunca haber vereceğim.",
        "project_made": "Proje hazır: {name}. /yeni yazarak ilk geliştirmeyi başlatabilirsin.",
        "project_failed": "Proje kurulamadı: {why}",
        "cancelled": "Tamam, vazgeçtim.",
        "not_owner": "Bu hesapta iş başlatmak hesabın sahibine ait.",
        "not_verified": "Önce e-posta adresini doğrulaman gerekiyor.",
        "demo": "Örnek proje salt okunur; kendi projende dene.",
        "pick_again": "Anlamadım. Listeden bir numara ya da ad yaz.\n(vazgeçmek için /iptal)",
        "refused": "Olmadı: {why}",
    },
    "en": {
        "unknown": (
            "I do not know that one. You can ask: which projects there are, how a project "
            "is doing, what is waiting for you, what is running, what it cost."
        ),
        "too_many": "That is a lot of questions; try again a little later.",
        "no_projects": "You have no projects yet.",
        "nothing_waiting": "Nothing is waiting for you.",
        "nothing_running": "Nothing is being worked on right now.",
        "no_such_project": "I could not find that project.",
        "which_project": "Which project? Give its number or its name.\n{list}",
        "what_request": "What should be built? One sentence.\n(/cancel to stop)",
        "started": "Started: {project} — {request}\nI will come back to you at the first gate.",
        "project_name": "What should the new project be called?\n(/cancel to stop)",
        "project_repo": (
            "Which repository? Write it as {owner}/name.\nFor a folder on your own machine "
            "write its path, or - for no repository."
        ),
        "project_making": "Setting up {name}. I will tell you when it is ready.",
        "project_made": "{name} is ready. Type /new to start the first development.",
        "project_failed": "The project could not be set up: {why}",
        "cancelled": "Fine, dropped it.",
        "not_owner": "Starting work belongs to the owner of the account.",
        "not_verified": "Confirm your email address first.",
        "demo": "The example project is read-only; try it on one of your own.",
        "pick_again": "I did not follow. Give a number or a name from the list.\n(/cancel to stop)",
        "refused": "That did not work: {why}",
    },
}


def _say(lang: str, key: str, **kw: Any) -> str:
    table = WORDS.get(lang, WORDS["en"])
    return table[key].format(**kw) if kw else table[key]


class Question(BaseModel):
    """Which of the six was asked, and about what."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    project: str = Field(
        default="", description="The project the question is about, as the person named it."
    )


class Written(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


# --- step 1: which question -------------------------------------------------------------


def command_of(text: str) -> tuple[Intent | None, str]:
    """The intent a typed command carries, and whatever followed it."""
    head, _, rest = text.strip().partition(" ")
    return COMMANDS.get(head.lstrip("/").lower()), rest.strip()


def classify(
    text: str, *, provider: ModelProvider, profile: Profile, timeout_s: float = 30.0
) -> Question:
    """Which question a sentence is. ``unknown`` whenever it is not clearly one of them,
    including when the model cannot be reached: a wrong guess reads worse than a shrug."""
    options = ", ".join(
        [
            "projects (which projects exist)",
            "status (how a project or development is doing, what step it is at)",
            "waiting (what is waiting for the person to approve)",
            "running (what is being worked on right now)",
            "cost (what has been spent)",
            "unknown (anything else at all)",
        ]
    )
    cfg = profile.roles[RoleName.PO]
    request = ModelRequest(
        role=RoleName.PO,
        model=cfg.model,
        provider=cfg.provider,
        thinking_depth=ThinkingDepth.OFF,
        permissions=(),
        system=_SYSTEM,
        prompt=(
            f"Which of these is the message asking for?\n{options}\n\n"
            "If it names a project, put that name in `project`, exactly as written.\n"
            "Answer `unknown` unless it is clearly one of the others.\n\n"
            + json.dumps({"message": text}, ensure_ascii=False)
            + "\n\nRespond with one JSON object matching this JSON Schema:\n"
            + json.dumps(Question.model_json_schema(), indent=2, sort_keys=True)
        ),
        output_schema=Question.model_json_schema(),
        timeout_s=timeout_s,
    )
    try:
        return Question.model_validate_json(_unfenced(provider.complete(request).text))
    except (ProviderError, ValueError, TypeError) as exc:
        log.info("ask: could not classify %r: %s", text[:60], exc)
        return Question(intent="unknown")
    except Exception as exc:  # noqa: BLE001 - a chat message must never raise
        log.warning("ask: could not classify %r: %r", text[:60], exc)
        return Question(intent="unknown")


def _unfenced(text: str) -> str:
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    return body.strip()


# --- step 2: the rows, read here and scoped to this account -------------------------------


def _pending(job: Job) -> str | None:
    """What this development is waiting for a person to say, if anything."""
    if job.state not in APPROVAL_STATES:
        return None
    if job.state is JobState.AWAITING_TEST_APPROVAL:
        return "test cases" if job.data.qa_stage == 1 else "written tests"
    return job.state.value.removeprefix("awaiting_").removesuffix("_approval").replace("_", " ")


def _headline(request: str) -> str:
    line = request.strip().splitlines()[0] if request.strip() else ""
    return line[:80] + "…" if len(line) > 80 else line


def gather(notifier: Notifier, user_id: str, question: Question) -> dict[str, Any]:
    """The answer, read from the store as the account the chat is linked to.

    Every read carries the owner, so this cannot reach another account's work however the
    question was phrased -- the same rule the pages follow, applied at the one place a
    stranger's sentence gets near the data.
    """
    engine = notifier.engine.for_user(user_id)
    owner = notifier.owner_key or None
    store = engine.store
    projects = store.list_projects(owner)
    named = _match(projects, question.project)
    jobs = [j for j in store.list(owner_id=owner)]
    by_project = {p.id: p.name for p in projects}

    if question.intent == "projects":
        return {
            "projects": [
                {
                    "name": p.name,
                    "repository": p.github_repo or str(p.repo_path or ""),
                    "developments": sum(1 for j in jobs if j.project_id == p.id),
                    "waiting_for_you": sum(
                        1 for j in jobs if j.project_id == p.id and j.state in APPROVAL_STATES
                    ),
                }
                for p in projects
            ]
        }

    if question.intent == "waiting":
        return {
            "waiting": [
                {
                    "project": by_project.get(j.project_id or "", ""),
                    "request": _headline(j.request),
                    "waiting_for": _pending(j),
                }
                for j in jobs
                if j.state in APPROVAL_STATES
            ]
        }

    if question.intent == "running":
        return {
            "running": [
                {
                    "project": by_project.get(j.project_id or "", ""),
                    "request": _headline(j.request),
                    "step": j.state.value,
                }
                for j in jobs
                if not j.is_terminal and j.state not in APPROVAL_STATES
            ]
        }

    if question.intent == "cost":
        wanted = [named] if named else projects
        return {
            "cost": [
                {
                    "project": p.name,
                    "spent_usd": round(
                        sum(j.data.cost_usd for j in jobs if j.project_id == p.id), 4
                    ),
                    "developments": sum(1 for j in jobs if j.project_id == p.id),
                }
                for p in wanted
            ]
        }

    if question.intent == "status":
        if question.project and named is None:
            return {"error": "no_such_project"}
        wanted = [named] if named else projects
        return {
            "status": [
                {
                    "project": p.name,
                    "developments": [
                        {
                            "request": _headline(j.request),
                            "step": j.state.value,
                            "waiting_for": _pending(j),
                            "finished": j.is_terminal,
                        }
                        # the newest first, and never the whole history of a busy project
                        for j in sorted(
                            (j for j in jobs if j.project_id == p.id),
                            key=lambda j: j.created_at,
                            reverse=True,
                        )[:3]
                    ],
                }
                for p in wanted
            ]
        }
    return {}


def _match(projects: list[Any], name: str) -> Any | None:
    """The project somebody meant by what they typed, or None."""
    wanted = name.strip().casefold()
    if not wanted:
        return None
    for project in projects:
        if project.name.casefold() == wanted:
            return project
    for project in projects:
        if wanted in project.name.casefold():
            return project
    return None


# --- step 3: the sentence -----------------------------------------------------------------


def plain(lang: str, data: dict[str, Any]) -> str:
    """The answer without a model: a list a person can read. Used when the model is not
    reachable, and as the thing the written answer must not contradict."""
    if data.get("error") == "no_such_project":
        return _say(lang, "no_such_project")
    if "projects" in data:
        rows = data["projects"]
        if not rows:
            return _say(lang, "no_projects")
        return "\n".join(
            f"• {r['name']} — {r['developments']}"
            + (f" ⏳{r['waiting_for_you']}" if r["waiting_for_you"] else "")
            for r in rows
        )
    if "waiting" in data:
        rows = data["waiting"]
        if not rows:
            return _say(lang, "nothing_waiting")
        return "\n".join(f"• {r['project']}: {r['request']} → {r['waiting_for']}" for r in rows)
    if "running" in data:
        rows = data["running"]
        if not rows:
            return _say(lang, "nothing_running")
        return "\n".join(f"• {r['project']}: {r['request']} → {r['step']}" for r in rows)
    if "cost" in data:
        rows = data["cost"]
        if not rows:
            return _say(lang, "no_projects")
        return "\n".join(f"• {r['project']}: ${r['spent_usd']:.3f}" for r in rows)
    if "status" in data:
        rows = data["status"]
        if not rows:
            return _say(lang, "no_projects")
        out: list[str] = []
        for row in rows:
            out.append(f"• {row['project']}")
            for dev in row["developments"]:
                mark = "✓" if dev["finished"] else ("⏳" if dev["waiting_for"] else "…")
                out.append(f"   {mark} {dev['request']} → {dev['waiting_for'] or dev['step']}")
        return "\n".join(out)
    return _say(lang, "unknown")


def write(
    data: dict[str, Any],
    *,
    lang: str,
    provider: ModelProvider,
    profile: Profile,
    timeout_s: float = 30.0,
) -> str:
    """The rows as a sentence, in the person's language. Falls back to the plain listing,
    which is never worse than a model's guess at data it was not given."""
    fallback = plain(lang, data)
    cfg = profile.roles[RoleName.PO]
    request = ModelRequest(
        role=RoleName.PO,
        model=cfg.model,
        provider=cfg.provider,
        thinking_depth=ThinkingDepth.OFF,
        permissions=(),
        system=_WRITE_SYSTEM,
        prompt=(
            f"Write the answer in {lang}, for a chat app: a couple of lines, no heading, "
            "no markdown table. Keep every project name exactly as it is written here. "
            "Say only what the data says.\n\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
            + "\n\nRespond with one JSON object matching this JSON Schema:\n"
            + json.dumps(Written.model_json_schema(), indent=2, sort_keys=True)
        ),
        output_schema=Written.model_json_schema(),
        timeout_s=timeout_s,
    )
    try:
        written = Written.model_validate_json(_unfenced(provider.complete(request).text))
    except (ProviderError, ValueError, TypeError) as exc:
        log.info("ask: could not write the answer: %s", exc)
        return fallback
    except Exception as exc:  # noqa: BLE001 - a chat message must never raise
        log.warning("ask: could not write the answer: %r", exc)
        return fallback
    return written.text.strip() or fallback


# --- the conversations that write something ------------------------------------------------


def _dialog_store(notifier: Notifier, user_id: str) -> Any:
    return notifier.engine.for_user(user_id).store


def _dialog(notifier: Notifier, user_id: str) -> dict[str, Any] | None:
    """The conversation in progress, or None when there is none or it has gone stale."""
    saved: dict[str, Any] = _dialog_store(notifier, user_id).get_setting(DIALOG, {}) or {}
    if not saved.get("flow"):
        return None
    try:
        started = datetime.fromisoformat(str(saved.get("at", "")))
    except ValueError:
        return None
    if (utcnow() - started).total_seconds() > DIALOG_LIFE_S:
        _forget(notifier, user_id)
        return None
    return saved


def _remember(notifier: Notifier, user_id: str, **state: Any) -> None:
    _dialog_store(notifier, user_id).set_setting(DIALOG, {**state, "at": utcnow().isoformat()})


def _forget(notifier: Notifier, user_id: str) -> None:
    _dialog_store(notifier, user_id).delete_setting(DIALOG)


def _may_start(notifier: Notifier, user_id: str) -> str | None:
    """Why this person may not start work here, or None. The chat twin of the API's
    ``require_owner`` and ``require_verified``."""
    try:
        user = notifier.store.get_user(user_id)
    except KeyError:
        return "not_owner"
    if getattr(user, "is_member", False):
        return "not_owner"
    if getattr(user, "email", None) and getattr(user, "email_verified_at", None) is None:
        return "not_verified"
    return None


def _listed(projects: list[Any]) -> str:
    return "\n".join(f"{i}. {p.name}" for i, p in enumerate(projects, start=1))


def _chosen(projects: list[Any], answer: str) -> Any | None:
    """The project a person picked by number or by name."""
    picked = answer.strip()
    if picked.isdigit() and 1 <= int(picked) <= len(projects):
        return projects[int(picked) - 1]
    return _match(projects, picked)


def begin(notifier: Notifier, user_id: str, flow: str) -> str:
    """The first question of a conversation that will write something."""
    refusal = _may_start(notifier, user_id)
    if refusal:
        return _say(notifier.lang, refusal)
    engine = notifier.engine.for_user(user_id)
    if flow == "new_project":
        _remember(notifier, user_id, flow=flow, step="name", data={})
        return _say(notifier.lang, "project_name")
    projects = [p for p in engine.store.list_projects(notifier.owner_key or None) if not p.is_demo]
    if not projects:
        return _say(notifier.lang, "no_projects")
    if len(projects) == 1:
        # one project is not a question worth asking
        _remember(
            notifier, user_id, flow=flow, step="request", data={"project_id": projects[0].id}
        )
        return _say(notifier.lang, "what_request")
    _remember(notifier, user_id, flow=flow, step="project", data={})
    return _say(notifier.lang, "which_project", list=_listed(projects))


def carry_on(notifier: Notifier, user_id: str, state: dict[str, Any], text: str) -> str:
    """The next step of a conversation, given what was just typed."""
    lang = notifier.lang
    engine = notifier.engine.for_user(user_id)
    owner = notifier.owner_key or None
    flow, step = str(state.get("flow")), str(state.get("step"))
    data: dict[str, Any] = dict(state.get("data") or {})

    if flow == "new_job":
        if step == "project":
            projects = [p for p in engine.store.list_projects(owner) if not p.is_demo]
            project = _chosen(projects, text)
            if project is None:
                return _say(lang, "pick_again")
            data["project_id"] = project.id
            _remember(notifier, user_id, flow=flow, step="request", data=data)
            return _say(lang, "what_request")
        if step == "request":
            _forget(notifier, user_id)
            return _start_job(notifier, user_id, str(data.get("project_id") or ""), text)

    if flow == "new_project":
        if step == "name":
            data["name"] = text.strip()
            _remember(notifier, user_id, flow=flow, step="repo", data=data)
            source = engine.default_source()
            rows = {r.name: r for r in engine.source_settings()}
            row = rows.get(source)
            return _say(lang, "project_repo", owner=(row.owner if row else None) or "owner")
        if step == "repo":
            _forget(notifier, user_id)
            return _make_project(notifier, user_id, str(data.get("name") or ""), text.strip())

    _forget(notifier, user_id)
    return _say(lang, "cancelled")


def _start_job(notifier: Notifier, user_id: str, project_id: str, request: str) -> str:
    """Create the development and let it run, the way the page does."""
    lang = notifier.lang
    engine = notifier.engine.for_user(user_id)
    owner = notifier.owner_key or None
    if not request.strip():
        return _say(lang, "cancelled")
    try:
        project = engine.store.get_project(project_id, owner)
    except Exception:  # noqa: BLE001 - it was deleted while the question was open
        return _say(lang, "no_such_project")
    if project.is_demo:
        return _say(lang, "demo")
    try:
        engine.quotas.check_new_job(user_id)
    except QuotaExceeded as exc:
        return _say(lang, "refused", why=str(exc))
    except AttributeError:  # an engine built without quotas
        pass
    try:
        job = engine.create_job(request.strip(), project_id=project.id)
    except Exception as exc:  # noqa: BLE001 - whatever it was, it is the person's answer
        log.warning("ask: could not start a development: %r", exc)
        return _say(lang, "refused", why=str(exc))
    notifier.resume(job.id)
    return _say(lang, "started", project=project.name, request=_headline(request))


def _make_project(notifier: Notifier, user_id: str, name: str, repo: str) -> str:
    """Open the project and answer at once; the clone runs behind and speaks for itself.

    A clone is a network call to somebody else's server: holding the chat open for it
    would stall the bot's whole polling loop, and a person watching a spinner in a chat
    window learns nothing.
    """
    lang = notifier.lang
    if not name:
        return _say(lang, "cancelled")
    engine = notifier.engine.for_user(user_id)
    try:
        engine.quotas.check_new_project(user_id)
    except QuotaExceeded as exc:
        return _say(lang, "refused", why=str(exc))
    except AttributeError:
        pass

    fields: dict[str, Any] = {"name": name, "owner_id": notifier.owner_key or None}
    answer = repo.strip()
    if answer and answer != "-":
        if "/" in answer and not Path(answer).is_absolute():
            fields["github_repo"] = answer
            fields["source"] = engine.default_source()
        else:
            fields["repo_path"] = Path(answer)

    def run() -> None:
        try:
            made = engine.create_project(Project(**fields))
            said = _say(lang, "project_made", name=made.name)
        except Exception as exc:  # noqa: BLE001 - a background thread has nobody to raise to
            log.info("ask: could not create %s: %r", name, exc)
            said = _say(lang, "project_failed", why=str(exc))
        _tell(notifier, user_id, said)

    threading.Thread(target=run, daemon=True).start()
    return _say(lang, "project_making", name=name)


def _tell(notifier: Notifier, user_id: str, text: str) -> None:
    """Send a follow-up to every chat this person has linked."""
    for channel in ("telegram", "slack", "discord", "teams"):
        adapter = notifier.adapter(channel)
        if adapter is None or not getattr(adapter, "has_bot", False):
            continue
        for link in notifier.store.chat_links(notifier.owner_key, channel=channel, user_id=user_id):
            try:
                adapter.say(link.address, text)
            except Exception as exc:  # noqa: BLE001 - one channel being down is not the others'
                log.info("ask: could not follow up on %s: %r", channel, exc)


# --- the whole of it ----------------------------------------------------------------------


def ask(notifier: Notifier, *, user_id: str, text: str) -> str | None:
    """Answer a question typed into a linked chat, or None when it is not a question.

    ``None`` leaves the bot silent, which is what somebody chatting in a group wants.
    """
    head, _, rest_of = text.strip().partition(" ")
    typed = head.lstrip("/").lower()
    if typed in CANCEL:
        _forget(notifier, user_id)
        return _say(notifier.lang, "cancelled")
    if typed in FLOWS:
        return begin(notifier, user_id, FLOWS[typed])
    # a conversation already under way owns whatever is typed next, so "login ekle" is
    # read as the answer it is rather than as a question about the word "login"
    waiting = _dialog(notifier, user_id)
    if waiting is not None:
        return carry_on(notifier, user_id, waiting, text.strip())

    intent, rest = command_of(text)
    if intent is None and text.strip().startswith("/"):
        return None  # a command meant for something else
    store = notifier.store
    bucket = f"ask:{notifier.owner_key or '-'}:{user_id}"
    if store.hit_rate_limit(bucket, limit=ASK_LIMIT, window_s=ASK_WINDOW_S):
        return _say(notifier.lang, "too_many")

    engine = notifier.engine.for_user(user_id)
    profile = engine.seed_profile
    provider: ModelProvider | None
    try:
        provider = engine.provider
    except Exception as exc:  # noqa: BLE001 - no key, no model: the listing still works
        log.info("ask: no provider for %s: %s", user_id, exc)
        provider = None

    if intent is not None:
        # a typed command is already the answer to "which question is this", and its rows
        # read perfectly well as a list: there is nothing for a model to add, and asking
        # one anyway would bill somebody for typing /projeler
        question = Question(intent=intent, project=rest)
        try:
            return plain(notifier.lang, gather(notifier, user_id, question))
        except Exception as exc:  # noqa: BLE001 - a chat message must never raise
            log.warning("ask: could not read the answer to %s: %r", question.intent, exc)
            return None
    if provider is None:
        return None  # a sentence needs a model to be understood at all
    else:
        question = classify(text, provider=provider, profile=profile)

    if question.intent == "unknown":
        return _say(notifier.lang, "unknown")
    try:
        data = gather(notifier, user_id, question)
    except Exception as exc:  # noqa: BLE001 - a chat message must never raise
        log.warning("ask: could not read the answer to %s: %r", question.intent, exc)
        return None
    if provider is None:
        return plain(notifier.lang, data)
    return write(data, lang=notifier.lang, provider=provider, profile=profile)


__all__ = [
    "ASK_LIMIT",
    "COMMANDS",
    "DIALOG",
    "FLOWS",
    "Intent",
    "Question",
    "ask",
    "begin",
    "carry_on",
    "classify",
    "command_of",
    "gather",
    "plain",
    "write",
]
