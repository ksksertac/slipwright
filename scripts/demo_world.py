"""The world outside Slipwright, for the demo: Telegram, Jira and a Git host, all local.

The README's recording shows a development reaching a person on their phone, its tasks
moving across a Jira board and its branch being pushed. Real services would make every
take depend on a bot token, a Jira site and a repository somebody can see -- and would
make it cost something and differ each time. So the services are stood in for here, at
the one seam Slipwright already has for it: every call the engine makes to Telegram and
Jira goes through ``engine.http_transport``, and every push through ``engine._git_host``.

Nothing about Slipwright is faked. The bot's messages are what ``notify/`` writes, a
button pressed on the phone goes through ``handle_update`` and ``Notifier.on_press`` --
the same guard, the same approval -- and the Jira issues are the ones ``JiraSync`` opens
and moves. Only what is on the other end of the wire is ours: a Bot API that keeps its
messages in a list, and a Jira that keeps its issues in a dict. Each has a page of its
own (``/demo/telegram``, ``/demo/jira``) for the recording to point a browser at.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse

from slipwright.githost import CiState, CiStatus

HERE = Path(__file__).resolve().parent

#: Who is on the phone. The name the bot addresses and the one "Approved by" shows.
PERSON = {"id": 4242, "first_name": "Ada", "username": "ada"}
BOT = {"id": 777, "is_bot": True, "first_name": "Slipwright", "username": "SlipwrightBot"}

#: Where the Jira stand-in says it lives; shown on the new-project form.
JIRA_SITE = "https://acme.atlassian.net"
JIRA_PROJECT = {"key": "NOTES", "name": "Notes", "id": "10001"}


def _clock() -> str:
    return time.strftime("%H:%M")


class Telegram:
    """A Bot API with one chat in it: the person's, with the bot."""

    def __init__(self) -> None:
        self.lock = threading.Condition()
        self.messages: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.toast: dict[str, Any] | None = None
        self._ids = itertools.count(1)
        self._update_ids = itertools.count(1)

    # -- the wire ------------------------------------------------------------------------

    def answer(self, method: str, body: dict[str, Any]) -> Any:
        if method == "getMe":
            return BOT
        if method in ("deleteWebhook", "setMyCommands"):
            return True
        if method == "getUpdates":
            return self._wait(body.get("offset", 0), float(body.get("timeout", 0)))
        if method == "sendMessage":
            with self.lock:
                msg = {
                    "message_id": next(self._ids),
                    "from": "bot",
                    "text": body.get("text", ""),
                    "buttons": _buttons(body.get("reply_markup")),
                    "at": _clock(),
                }
                self.messages.append(msg)
                self.lock.notify_all()
            return {"message_id": msg["message_id"], "chat": {"id": PERSON["id"]}}
        if method in ("editMessageText", "editMessageReplyMarkup"):
            with self.lock:
                for msg in self.messages:
                    if msg["message_id"] == body.get("message_id"):
                        if "text" in body:
                            msg["text"] = body["text"]
                        msg["buttons"] = _buttons(body.get("reply_markup"))
                self.lock.notify_all()
            return True
        if method == "answerCallbackQuery":
            with self.lock:
                self.toast = {"text": body.get("text", ""), "at": time.time()}
            return True
        return True

    def _wait(self, offset: int, timeout: float) -> list[dict[str, Any]]:
        # long polling, as Telegram does it: hold the call until there is something or the
        # timeout is up, so a press reaches the bot at once rather than on the next poll
        end = time.monotonic() + min(timeout, 25.0)
        with self.lock:
            while True:
                waiting = [u for u in self.updates if u["update_id"] >= offset]
                left = end - time.monotonic()
                if waiting or left <= 0:
                    return waiting
                self.lock.wait(left)

    # -- the phone -----------------------------------------------------------------------

    def press(self, message_id: int, data: str) -> None:
        with self.lock:
            msg = next((m for m in self.messages if m["message_id"] == message_id), None)
            label = next(
                (
                    b["text"]
                    for row in (msg or {}).get("buttons", [])
                    for b in row
                    if b["data"] == data
                ),
                data,
            )
            self.messages.append(
                {"message_id": next(self._ids), "from": "pressed", "text": label, "at": _clock()}
            )
            self.updates.append(
                {
                    "update_id": next(self._update_ids),
                    "callback_query": {
                        "id": f"cb{message_id}",
                        "from": PERSON,
                        "data": data,
                        "message": {"message_id": message_id, "chat": {"id": PERSON["id"]}},
                    },
                }
            )
            self.lock.notify_all()

    def say(self, text: str) -> None:
        with self.lock:
            self.messages.append(
                {"message_id": next(self._ids), "from": "me", "text": text, "at": _clock()}
            )
            self.updates.append(
                {
                    "update_id": next(self._update_ids),
                    "message": {
                        "message_id": 0,
                        "from": PERSON,
                        "chat": {"id": PERSON["id"], "type": "private"},
                        "text": text,
                    },
                }
            )
            self.lock.notify_all()

    def state(self) -> dict[str, Any]:
        with self.lock:
            return {"messages": list(self.messages), "toast": self.toast}


def _buttons(markup: Any) -> list[list[dict[str, str]]]:
    rows = (markup or {}).get("inline_keyboard") or []
    return [
        [{"text": b.get("text", ""), "data": b.get("callback_data", "")} for b in r] for r in rows
    ]


class Jira:
    """One Jira project with a Scrum board and a sprint already running."""

    STATUSES = ("To Do", "In Progress", "Done")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.issues: dict[str, dict[str, Any]] = {}
        self.sprint = {"id": 7, "name": "NOTES Sprint 7", "state": "active"}
        self._n = itertools.count(1)

    def answer(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        with self.lock:
            return self._answer(method, path, body)

    def _answer(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        parts = path.strip("/").split("/")
        if path == "/rest/api/3/myself":
            return 200, {"accountId": "ada", "displayName": "Ada", "emailAddress": "ada@acme.dev"}
        if path == "/rest/api/3/project/search":
            return 200, {"values": [JIRA_PROJECT]}
        if path.startswith("/rest/api/3/issue/createmeta/"):
            return 200, {
                "issueTypes": [
                    {"name": "Epic", "subtask": False, "hierarchyLevel": 1},
                    {"name": "Story", "subtask": False, "hierarchyLevel": 0},
                    {"name": "Subtask", "subtask": True, "hierarchyLevel": -1},
                ]
            }
        if path == "/rest/api/3/issue" and method == "POST":
            fields = body.get("fields") or {}
            key = f"{JIRA_PROJECT['key']}-{next(self._n)}"
            self.issues[key] = {
                "key": key,
                "type": (fields.get("issuetype") or {}).get("name", "Task"),
                "summary": fields.get("summary", ""),
                "parent": (fields.get("parent") or {}).get("key"),
                "status": "To Do",
                "comments": [],
                "sprint": False,
                "created": time.time(),
            }
            return 201, {"key": key, "id": key}
        if parts[:4] == ["rest", "api", "3", "issue"] and len(parts) >= 5:
            issue = self.issues.get(parts[4])
            if issue is None:
                return 404, {"errorMessages": ["Issue does not exist"]}
            tail = parts[5] if len(parts) > 5 else ""
            if tail == "transitions" and method == "GET":
                return 200, {
                    "transitions": [
                        {"id": str(i + 1), "name": s, "to": {"name": s}}
                        for i, s in enumerate(self.STATUSES)
                    ]
                }
            if tail == "transitions":
                wanted = int((body.get("transition") or {}).get("id", 1)) - 1
                issue["status"] = self.STATUSES[wanted]
                issue["moved"] = time.time()
                return 204, None
            if tail == "comment":
                issue["comments"].append(_plain(body.get("body")))
                return 201, {"id": str(len(issue["comments"]))}
            if tail == "worklog":
                return 201, {}
            return 200, {"key": issue["key"], "fields": {"status": {"name": issue["status"]}}}
        if path == "/rest/api/3/issueLink":
            return 201, None
        if path == "/rest/agile/1.0/board":
            return 200, {"values": [{"id": 1, "type": "scrum", "name": "NOTES board"}]}
        if path == "/rest/agile/1.0/board/1/sprint":
            return 200, {"values": [self.sprint]}
        if path == f"/rest/agile/1.0/sprint/{self.sprint['id']}/issue":
            for key in body.get("issues") or []:
                if key in self.issues:
                    self.issues[key]["sprint"] = True
                    for child in self.issues.values():
                        if child["parent"] == key:
                            child["sprint"] = True
            return 204, None
        return 404, {"errorMessages": [f"the demo Jira has no {method} {path}"]}

    def state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "project": JIRA_PROJECT,
                "sprint": self.sprint,
                "issues": sorted(self.issues.values(), key=lambda i: i["created"]),
            }


def _plain(doc: Any) -> str:
    """Atlassian Document Format back to text: what the comment said."""
    if not isinstance(doc, dict):
        return str(doc or "")
    out: list[str] = []
    for para in doc.get("content") or []:
        out.append("".join(n.get("text", "") for n in para.get("content") or []))
    return "\n".join(out)


def transport(telegram: Telegram, jira: Jira) -> httpx.MockTransport:
    """Every outbound call the engine makes, answered here. Anything else is refused, so a
    take that reaches for the real internet fails loudly rather than quietly succeeding."""
    jira_host = httpx.URL(JIRA_SITE).host

    def handle(request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = {}
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = {}
        if request.url.host == "api.telegram.org":
            method = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"ok": True, "result": telegram.answer(method, body)})
        if request.url.host == jira_host:
            status, data = jira.answer(request.method, request.url.path, body)
            if data is None:
                return httpx.Response(status)
            return httpx.Response(status, json=data)
        return httpx.Response(503, json={"error": f"the demo is offline: {request.url}"})

    return httpx.MockTransport(handle)


class Host:
    """A Git host whose pushes are real and whose pull request is a number.

    The branch really is pushed -- into a bare repository standing in for GitHub -- so the
    push the recording shows is one that happened. The pull request and its checks are
    the part with nothing behind them.
    """

    def __init__(self, remote: Path, url: str) -> None:
        self.remote = remote
        self.url = url.rstrip("/")
        self.pushed: list[str] = []

    def push(self, worktree: Path, branch: str) -> None:
        subprocess.run(
            ["git", "push", "-q", str(self.remote), f"HEAD:refs/heads/{branch}"],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
        self.pushed.append(branch)

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        return f"{self.url}/pull/42"

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        return CiStatus(CiState.SUCCESS, summary="3 checks passed: lint, tests, docker build")


def pages(app: FastAPI, telegram: Telegram, jira: Jira) -> None:
    """The phone and the board, as pages the recording can open beside Slipwright.

    Put at the front of the app's routes: the app ends in a catch-all that serves the web
    UI for any path it does not know, and a route added after it would never be reached.
    Not a mounted sub-app either -- Starlette runs no lifespan for the app underneath a
    mount, and the lifespan is what starts the chat bot.
    """
    outer = APIRouter()  # not FastAPI(): that brings /docs and /openapi.json with it

    def page(name: str) -> HTMLResponse:
        return HTMLResponse((HERE / name).read_text(encoding="utf-8"))

    @outer.get("/demo/telegram", include_in_schema=False)
    def telegram_page() -> HTMLResponse:
        return page("demo-telegram.html")

    @outer.get("/demo/telegram/state", include_in_schema=False)
    def telegram_state() -> dict[str, Any]:
        return telegram.state()

    @outer.post("/demo/telegram/press", include_in_schema=False)
    def telegram_press(body: dict[str, Any]) -> dict[str, bool]:
        telegram.press(int(body["message_id"]), str(body["data"]))
        return {"ok": True}

    @outer.post("/demo/telegram/say", include_in_schema=False)
    def telegram_say(body: dict[str, Any]) -> dict[str, bool]:
        telegram.say(str(body["text"]))
        return {"ok": True}

    @outer.get("/demo/jira", include_in_schema=False)
    def jira_page() -> HTMLResponse:
        return page("demo-jira.html")

    @outer.get("/demo/jira/state", include_in_schema=False)
    def jira_state() -> dict[str, Any]:
        return jira.state()

    app.router.routes[0:0] = outer.routes


__all__ = [
    "BOT",
    "JIRA_PROJECT",
    "JIRA_SITE",
    "PERSON",
    "Host",
    "Jira",
    "Telegram",
    "pages",
    "transport",
]
