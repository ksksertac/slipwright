"""Jira actions agents return and the engine executes (T7.5).

A role never holds a Jira credential: it *returns* ``jira_actions`` in its structured
result and the engine runs them through the agent account after checking that the role
has ``Permission.JIRA`` and that every issue belongs to the project's Jira project. Each
action carries a content-derived idempotency key, so executing the same result twice
(a restart mid-phase) never repeats an action. When Jira is unreachable the remaining
actions are queued on the job and retried on the next transition.
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


class ActionRunner:
    """Executes a role's actions for one job. The engine owns the client and persists
    ``job.data`` afterwards."""

    def __init__(self, client: JiraClient | None, project: Project) -> None:
        self.client = client
        self.project = project

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
            outcomes.append(self._execute(job, role, action, entry["key"]))
        return outcomes

    def _confinement_problem(self, action: JiraAction) -> str | None:
        for field_name in ("issue", "parent", "target"):
            value = getattr(action, field_name)
            if value and not value.upper().startswith(f"{self.key}-"):
                return f"{field_name} {value} is outside project {self.key}"
        return None

    def _execute(self, job: Job, role: RoleName, action: JiraAction, key: str) -> ActionOutcome:
        if self.client is None:
            return ActionOutcome(
                action=action, key=key, status="refused", detail="Jira is not configured"
            )
        try:
            detail = self._call(action)
        except JiraError as exc:
            job.data.jira_queue.append(
                {"role": role.value, "key": key, "action": action.model_dump(mode="json")}
            )
            return ActionOutcome(action=action, key=key, status="queued", detail=str(exc))
        job.data.jira_done.append(key)
        return ActionOutcome(action=action, key=key, status="done", detail=detail)

    def _call(self, action: JiraAction) -> str:
        assert self.client is not None
        if action.action is JiraActionType.CREATE_ISSUE:
            created = self.client.create_issue(
                self.key,
                action.issue_type or "Task",
                action.summary or "",
                action.description or "",
                parent_key=action.parent,
            )
            return f"created {created}"
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
