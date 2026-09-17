"""In-process fakes for external HTTP services (GitHub, Jira), driven through httpx."""

from __future__ import annotations

import json
from typing import Any

import httpx


class FakeGitHub:
    """Answers the handful of GitHub REST calls Slipwright makes. No network."""

    def __init__(self, token: str = "ghp_secret", login: str = "octocat") -> None:
        self.token = token
        self.login = login
        self.repos: list[dict[str, Any]] = [
            {
                "full_name": f"{login}/demo",
                "private": False,
                "default_branch": "main",
                "html_url": f"https://github.com/{login}/demo",
                "description": "demo repo",
            },
            {
                "full_name": "acme/secret",
                "private": True,
                "default_branch": "trunk",
                "html_url": "https://github.com/acme/secret",
                "description": None,
            },
        ]
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        if request.url.path == "/user":
            return httpx.Response(
                200,
                json={"login": self.login, "name": "Octo Cat"},
                headers={"x-ratelimit-remaining": "4999", "x-ratelimit-limit": "5000"},
            )
        if request.url.path == "/user/repos":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=self.repos if page == 1 else [])
        return httpx.Response(404, json={"message": "Not Found"})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class FakeJira:
    """A tiny Jira Cloud: issues with keys, transitions, comments, worklogs, links."""

    def __init__(
        self,
        *,
        email: str = "bot@example.com",
        token: str = "jira_secret",
        project_key: str = "DEM",
        down: bool = False,
    ) -> None:
        self.email = email
        self.token = token
        self.project_key = project_key
        self.down = down
        self.issues: dict[str, dict[str, Any]] = {}
        self.comments: dict[str, list[str]] = {}
        self.worklogs: dict[str, list[dict[str, Any]]] = {}
        self.links: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.accounts: dict[str, str] = {email: "Slipwright Bot"}
        self.statuses: dict[str, str] = {}
        self.transitions: list[dict[str, str]] = [
            {"id": "11", "name": "To Do", "to": "To Do"},
            {"id": "21", "name": "In Progress", "to": "In Progress"},
            {"id": "31", "name": "Done", "to": "Done"},
        ]
        self._seq = 0

    def _auth_ok(self, request: httpx.Request) -> bool:
        import base64

        header = request.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            email, token = base64.b64decode(header[6:]).decode().split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        return email in self.accounts and token == self.token

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if self.down:
            raise httpx.ConnectError("jira is down")
        if not self._auth_ok(request):
            return httpx.Response(401, json={"errorMessages": ["Unauthorized"]})
        body: dict[str, Any] = {}
        if request.content:
            body = json.loads(request.content)
        if path == "/rest/api/3/myself":
            import base64

            email = base64.b64decode(request.headers["Authorization"][6:]).decode().split(":")[0]
            return httpx.Response(
                200,
                json={
                    "accountId": f"acc-{email}",
                    "displayName": self.accounts[email],
                    "emailAddress": email,
                },
            )
        if path == "/rest/api/3/project/search":
            return httpx.Response(
                200,
                json={
                    "values": [{"key": self.project_key, "name": "Demo", "id": "10000"}],
                    "isLast": True,
                },
            )
        if path == "/rest/api/3/issue" and request.method == "POST":
            fields = body["fields"]
            project = fields["project"]["key"]
            if project != self.project_key:
                return httpx.Response(400, json={"errors": {"project": "project does not exist"}})
            self._seq += 1
            key = f"{project}-{self._seq}"
            self.issues[key] = {
                "key": key,
                "summary": fields["summary"],
                "type": fields["issuetype"]["name"],
                "parent": (fields.get("parent") or {}).get("key"),
                "description": fields.get("description"),
            }
            self.statuses[key] = "To Do"
            return httpx.Response(201, json={"id": str(1000 + self._seq), "key": key})
        parts = path.split("/")  # ['', 'rest', 'api', '3', 'issue', KEY, ...]
        if len(parts) >= 6 and parts[4] == "issue":
            key = parts[5]
            if key not in self.issues:
                return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})
            rest = parts[6:]
            if rest == ["transitions"] and request.method == "GET":
                return httpx.Response(200, json={"transitions": self.transitions})
            if rest == ["transitions"] and request.method == "POST":
                tid = body["transition"]["id"]
                for t in self.transitions:
                    if t["id"] == tid:
                        self.statuses[key] = t["to"]
                        return httpx.Response(204)
                return httpx.Response(400, json={"errorMessages": ["bad transition"]})
            if rest == ["comment"] and request.method == "POST":
                self.comments.setdefault(key, []).append(_adf_text(body["body"]))
                return httpx.Response(201, json={"id": "1"})
            if rest == ["worklog"] and request.method == "POST":
                self.worklogs.setdefault(key, []).append(
                    {"seconds": body["timeSpentSeconds"], "note": _adf_text(body.get("comment"))}
                )
                return httpx.Response(201, json={"id": "1"})
            if not rest and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "key": key,
                        "fields": {
                            "summary": self.issues[key]["summary"],
                            "status": {"name": self.statuses[key]},
                        },
                    },
                )
        if path == "/rest/api/3/issueLink" and request.method == "POST":
            self.links.append(
                {
                    "type": body["type"]["name"],
                    "inward": body["inwardIssue"]["key"],
                    "outward": body["outwardIssue"]["key"],
                }
            )
            return httpx.Response(201)
        return httpx.Response(404, json={"errorMessages": [f"no route {request.method} {path}"]})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def _adf_text(doc: Any) -> str:
    """Flatten an Atlassian Document Format body (or a plain string) to text."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text":
                out.append(str(node.get("text", "")))
            for child in node.get("content", []) or []:
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(doc)
    return "".join(out)


__all__ = ["FakeGitHub", "FakeJira"]
