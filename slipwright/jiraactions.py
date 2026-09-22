"""Jira actions agents return and the engine executes (T7.5).

A role never holds a Jira credential: it *returns* ``jira_actions`` in its structured
result and the engine runs them through the agent account after checking that the role
has ``Permission.JIRA`` and that every issue belongs to the project's Jira project. Each
action carries a content-derived idempotency key, so executing the same result twice
(a restart mid-phase) never repeats an action. When Jira is unreachable the remaining
actions are queued on the job and retried on the next transition and by the PO's round;
an action that keeps failing is given up after ``MAX_QUEUE_ATTEMPTS`` rounds, with the
reason in the history, so the queue never loops forever.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from slipwright.board import job_epics
from slipwright.jira import JiraClient, JiraError
from slipwright.jirasync import DEFAULT_TRANSITIONS
from slipwright.roles.results import JiraAction, JiraActionType
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Permission, Profile, RoleName
from slipwright.schemas.project import Project


class ActionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: JiraAction
    key: str
    status: str  # done | refused | queued | skipped
    detail: str = ""

    def line(self) -> str:
        what = self.action.action.value
        target = self.action.issue or self.action.summary or ""
        return (
            f"{self.status}: {what} {target} {('- ' + self.detail) if self.detail else ''}".strip()
        )


MAX_QUEUE_ATTEMPTS = 5


class ActionRunner:
    """Executes a role's actions for one job. The engine owns the client and persists
    ``job.data`` afterwards."""

    def __init__(self, client: JiraClient | None, project: Project) -> None:
        self.client = client
        self.project = project
        self._types: list[dict[str, Any]] | None = None

    @property
    def key(self) -> str:
        return self.project.jira_project_key or ""

    def run(
        self, job: Job, role: RoleName, profile: Profile, actions: list[JiraAction]
    ) -> list[ActionOutcome]:
        outcomes: list[ActionOutcome] = []
        allowed = Permission.JIRA in profile.roles[role].permissions
        for action in actions:
            key = action.idempotency_key(role, job)
            if not allowed:
                outcomes.append(
                    ActionOutcome(
                        action=action,
                        key=key,
                        status="refused",
                        detail=f"role {role.value} lacks the jira permission",
                    )
                )
                continue
            if key in job.data.jira_done:
                outcomes.append(
                    ActionOutcome(
                        action=action, key=key, status="skipped", detail="already executed"
                    )
                )
                continue
            problem = self._confinement_problem(action)
            if problem:
                outcomes.append(
                    ActionOutcome(action=action, key=key, status="refused", detail=problem)
                )
                continue
            outcomes.append(self._execute(job, role, action, key))
        return outcomes

    def retry_queued(self, job: Job) -> list[ActionOutcome]:
        """Run actions queued by an earlier outage; leaves the rest queued on failure."""
        if not job.data.jira_queue:
            return []
        queued = list(job.data.jira_queue)
        job.data.jira_queue = []
        outcomes: list[ActionOutcome] = []
        for entry in queued:
            action = JiraAction.model_validate(entry["action"])
            role = RoleName(entry["role"])
            attempts = int(entry.get("attempts", 1))
            outcome = self._execute(job, role, action, entry["key"], attempts=attempts + 1)
            if outcome.status == "queued" and attempts + 1 >= MAX_QUEUE_ATTEMPTS:
                job.data.jira_queue.pop()  # _execute re-queued it; this was the last try
                outcome = ActionOutcome(
                    action=action,
                    key=entry["key"],
                    status="refused",
                    detail=f"gave up after {attempts + 1} attempts: {outcome.detail}",
                )
            outcomes.append(outcome)
        return outcomes

    def _confinement_problem(self, action: JiraAction) -> str | None:
        for field_name in ("issue", "parent", "target"):
            value = getattr(action, field_name)
            if value and not value.upper().startswith(f"{self.key}-"):
                return f"{field_name} {value} is outside project {self.key}"
        return None

    def _execute(
        self, job: Job, role: RoleName, action: JiraAction, key: str, *, attempts: int = 1
    ) -> ActionOutcome:
        if self.client is None:
            return ActionOutcome(
                action=action, key=key, status="refused", detail="Jira is not configured"
            )
        try:
            detail = self._call(action)
        except JiraError as exc:
            job.data.jira_queue.append(
                {
                    "role": role.value,
                    "key": key,
                    "action": action.model_dump(mode="json"),
                    "attempts": attempts,
                }
            )
            return ActionOutcome(action=action, key=key, status="queued", detail=str(exc))
        job.data.jira_done.append(key)
        return ActionOutcome(action=action, key=key, status="done", detail=detail)

    def _issue_types(self) -> list[dict[str, Any]]:
        if self._types is None:
            assert self.client is not None
            try:
                self._types = self.client.issue_types(self.key)
            except JiraError:
                self._types = []  # the create call will report the real problem
        return self._types

    def _create_issue(self, action: JiraAction) -> str:
        """A role names a type and maybe a parent; Jira Cloud only nests a sub-task type
        under a story. A Bug (or any other top-level type) that names a story as its
        parent is created at the top level and *linked* to the story instead — that is
        what the role meant. A type name the project does not have falls back to Task."""
        assert self.client is not None
        wanted = action.issue_type or "Task"
        parent = (action.parent or "").upper() or None
        types = self._issue_types()
        by_name = {t["name"].lower(): t for t in types}
        chosen = by_name.get(wanted.lower())
        note = ""
        if types and chosen is None:
            fallback = by_name.get("task") or next(
                (t for t in types if not t["subtask"] and t["level"] == 0), None
            )
            if fallback is not None:
                note = f" ({wanted!r} is not an issue type here; created as {fallback['name']})"
                chosen = fallback
        name = chosen["name"] if chosen else wanted
        link_to: str | None = None
        if parent and chosen is not None and not chosen["subtask"]:
            link_to, parent = parent, None
        created = self.client.create_issue(
            self.key,
            name,
            _clean(action.summary or ""),
            _clean(action.description or ""),
            parent_key=parent,
        )
        if link_to:
            self.client.link(created, link_to, "Relates")
            note += f", linked to {link_to}"
        return f"created {created}{note}"

    def _call(self, action: JiraAction) -> str:
        assert self.client is not None
        if action.action is JiraActionType.CREATE_ISSUE:
            return self._create_issue(action)
        assert action.issue is not None
        issue = action.issue.upper()
        if action.action is JiraActionType.TRANSITION:
            moved = self.client.transition(issue, action.to or "")
            return f"-> {action.to}" if moved else f"no transition named {action.to!r}; left as is"
        if action.action is JiraActionType.COMMENT:
            self.client.comment(issue, action.body or "")
            return "commented"
        if action.action is JiraActionType.LOG_WORK:
            self.client.log_work(issue, action.minutes or 1, action.note or "")
            return f"logged {action.minutes} min"
        self.client.link(issue, (action.target or "").upper(), action.link_type)
        return f"linked to {action.target}"


def _clean(text: str) -> str:
    """Model output occasionally carries lone surrogates (a mangled emoji); Jira rejects
    the request body for them, so they are replaced before anything is sent."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def jira_context(
    job: Job, role: RoleName, profile: Profile, project: Project
) -> dict[str, Any] | None:
    """What a role with the Jira permission is told: keys, statuses, transitions, rules."""
    if Permission.JIRA not in profile.roles[role].permissions or not project.jira_project_key:
        return None
    items: list[dict[str, Any]] = []
    current: str | None = None
    for epic in job_epics(job):
        items.append(_item("epic", epic.id, epic.title, epic.status.value, epic.jira_key))
        for story in epic.stories:
            items.append(_item("story", story.id, story.title, story.status.value, story.jira_key))
            for task in story.tasks:
                items.append(
                    {
                        **_item("task", task.id, task.title, task.status.value, task.jira_key),
                        "phase": task.phase,
                        "story_key": story.jira_key,
                    }
                )
                if task.phase is not None and task.phase - 1 == job.data.phase_index:
                    current = task.jira_key
    transitions = {**DEFAULT_TRANSITIONS, **project.jira_transitions}
    return {
        "project_key": project.jira_project_key,
        "current_task_key": current,
        "issues": [i for i in items if i["key"]],
        "transitions": {k: v for k, v in transitions.items() if v},
        "how": (
            "You may return `jira_actions` (create_issue, transition, comment, log_work, "
            "link_issues). Address existing issues by key instead of creating duplicates; "
            f"only issues in project {project.jira_project_key} are allowed. Keep comments "
            "short and factual."
        ),
    }


def _item(kind: str, item_id: str, title: str, status: str, key: str | None) -> dict[str, Any]:
    return {"kind": kind, "id": item_id, "title": title, "status": status, "key": key}


__all__ = [
    "ActionOutcome",
    "ActionRunner",
    "JiraAction",
    "JiraActionType",
    "jira_context",
]
