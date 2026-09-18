"""Jira Cloud REST v3 client: the handful of calls Slipwright makes.

Used by the settings page (who am I, which projects), by the engine's breakdown sync
(T7.4) and by agent-issued actions (T7.5). Bodies that Jira wants as Atlassian Document
Format are built from plain text here so callers only deal with strings. Tests pass an
``httpx`` transport that answers locally.
"""

from __future__ import annotations

import contextlib
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_ISSUE_TYPES = {"epic": "Epic", "story": "Story", "task": "Subtask", "bug": "Bug"}


class JiraError(RuntimeError):
    pass


class JiraAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    display_name: str
    email: str | None = None


class JiraProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    id: str | None = None


class JiraTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    to: str | None = None


class JiraSettings(BaseModel):
    """What the settings page reads and writes. Tokens are never returned."""

    model_config = ConfigDict(extra="forbid")

    site_url: str | None = Field(default=None, description="https://<site>.atlassian.net")
    email: str | None = None
    token_set: bool = False
    token_hint: str | None = None
    issue_types: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_ISSUE_TYPES))
    agent_email: str | None = Field(
        default=None, description="Separate account the agents act as (T7.5)."
    )
    agent_token_set: bool = False
    agent_token_hint: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.site_url and self.email and self.token_set)


def adf(text: str) -> dict[str, Any]:
    """Atlassian Document Format for plain text: one paragraph per line."""
    lines = text.splitlines() or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []}
            for line in lines
        ],
    }


class JiraClient:
    def __init__(
        self,
        site_url: str,
        email: str,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not (site_url and email and token):
            raise JiraError("Jira is not configured (site URL, e-mail and token are needed)")
        self.site_url = site_url.rstrip("/")
        self.email = email
        self._client = httpx.Client(
            base_url=self.site_url,
            auth=(email, token),
            headers={"Accept": "application/json", "User-Agent": "slipwright"},
            transport=transport,
            timeout=timeout,
        )

    # -- identity and projects -----------------------------------------------------------

    def myself(self) -> JiraAccount:
        data = self._request("GET", "/rest/api/3/myself").json()
        return JiraAccount(
            account_id=data.get("accountId", ""),
            display_name=data.get("displayName", ""),
            email=data.get("emailAddress"),
        )

    def list_projects(self) -> list[JiraProject]:
        data = self._request("GET", "/rest/api/3/project/search", params={"maxResults": 100}).json()
        return [
            JiraProject(key=p["key"], name=p.get("name", p["key"]), id=str(p.get("id") or ""))
            for p in data.get("values", [])
        ]

    # -- issues ----------------------------------------------------------------------------

    def create_issue(
        self,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str = "",
        *,
        parent_key: str | None = None,
    ) -> str:
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type},
            "summary": summary[:255],
        }
        if description:
            fields["description"] = adf(description)
        if parent_key:
            fields["parent"] = {"key": parent_key}
        data = self._request("POST", "/rest/api/3/issue", json={"fields": fields}).json()
        key: str = data["key"]
        return key

    def issue_types(self, project_key: str) -> list[dict[str, Any]]:
        """The issue types the project accepts: name, whether it is a sub-task and its
        hierarchy level (-1 sub-task, 0 story/task, 1 epic)."""
        data = self._request("GET", f"/rest/api/3/issue/createmeta/{project_key}/issuetypes").json()
        rows = data.get("issueTypes") or data.get("values") or []
        return [
            {
                "name": str(r.get("name")),
                "subtask": bool(r.get("subtask")),
                "level": int(r.get("hierarchyLevel", -1 if r.get("subtask") else 0)),
            }
            for r in rows
        ]

    def get_status(self, key: str) -> str:
        data = self._request("GET", f"/rest/api/3/issue/{key}", params={"fields": "status"})
        status: str = data.json()["fields"]["status"]["name"]
        return status

    def transitions(self, key: str) -> list[JiraTransition]:
        data = self._request("GET", f"/rest/api/3/issue/{key}/transitions").json()
        return [
            JiraTransition(
                id=str(t["id"]),
                name=t["name"],
                to=(t.get("to") or {}).get("name")
                if isinstance(t.get("to"), dict)
                else t.get("to"),
            )
            for t in data.get("transitions", [])
        ]

    def transition(self, key: str, name: str) -> bool:
        """Move an issue through the transition (or into the status) called ``name``.
        Returns False when the issue offers no such transition."""
        wanted = name.strip().lower()
        for t in self.transitions(key):
            if t.name.lower() == wanted or (t.to or "").lower() == wanted:
                self._request(
                    "POST",
                    f"/rest/api/3/issue/{key}/transitions",
                    json={"transition": {"id": t.id}},
                )
                return True
        return False

    def comment(self, key: str, text: str) -> None:
        self._request("POST", f"/rest/api/3/issue/{key}/comment", json={"body": adf(text)})

    def log_work(self, key: str, minutes: int, note: str = "") -> None:
        body: dict[str, Any] = {"timeSpentSeconds": max(60, int(minutes) * 60)}
        if note:
            body["comment"] = adf(note)
        self._request("POST", f"/rest/api/3/issue/{key}/worklog", json=body)

    def link(self, from_key: str, to_key: str, link_type: str = "Relates") -> None:
        self._request(
            "POST",
            "/rest/api/3/issueLink",
            json={
                "type": {"name": link_type},
                "inwardIssue": {"key": from_key},
                "outwardIssue": {"key": to_key},
            },
        )

    # -- sprints (Agile API) ---------------------------------------------------------------

    def board_id(self, project_key: str) -> int | None:
        """The project's first scrum board, or None (kanban / no board: no sprints)."""
        data = self._request(
            "GET",
            "/rest/agile/1.0/board",
            params={"projectKeyOrId": project_key, "type": "scrum"},
        ).json()
        boards = data.get("values") or []
        return int(boards[0]["id"]) if boards else None

    def active_sprint(self, board_id: int) -> dict[str, Any] | None:
        data = self._request(
            "GET", f"/rest/agile/1.0/board/{board_id}/sprint", params={"state": "active"}
        ).json()
        sprints = data.get("values") or []
        return dict(sprints[0]) if sprints else None

    def create_sprint(self, board_id: int, name: str, *, days: int = 14) -> dict[str, Any]:
        """Create and start a sprint of ``days`` from now."""
        from datetime import UTC, datetime, timedelta

        start = datetime.now(UTC)
        end = start + timedelta(days=days)
        created = self._request(
            "POST",
            "/rest/agile/1.0/sprint",
            json={"name": name[:255], "originBoardId": board_id},
        ).json()
        sprint_id = int(created["id"])
        started = self._request(
            "POST",
            f"/rest/agile/1.0/sprint/{sprint_id}",
            json={
                "state": "active",
                "startDate": start.isoformat(timespec="milliseconds"),
                "endDate": end.isoformat(timespec="milliseconds"),
            },
        ).json()
        return dict(started or created)

    def add_to_sprint(self, sprint_id: int, keys: list[str]) -> None:
        for i in range(0, len(keys), 50):  # the API takes 50 at a time
            self._request(
                "POST",
                f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                json={"issues": keys[i : i + 50]},
            )

    # -- plumbing --------------------------------------------------------------------------

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            resp = self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise JiraError(f"Jira request failed: {exc}") from exc
        if resp.status_code == 401:
            raise JiraError("Jira rejected the credentials (401)")
        if resp.status_code >= 400:
            message = ""
            with contextlib.suppress(ValueError):
                body = resp.json()
                message = "; ".join(
                    [
                        *body.get("errorMessages", []),
                        *(f"{k}: {v}" for k, v in body.get("errors", {}).items()),
                    ]
                )
            detail = message or resp.text[:200]
            raise JiraError(f"Jira returned {resp.status_code} for {method} {path}: {detail}")
        return resp


__all__ = [
    "DEFAULT_ISSUE_TYPES",
    "JiraAccount",
    "JiraClient",
    "JiraError",
    "JiraProject",
    "JiraSettings",
    "JiraTransition",
    "adf",
]
