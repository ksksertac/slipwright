"""Per-role structured result schemas.

Every role invocation must produce output that validates against the schema registered
for that role here. The invoke layer uses ``RESULT_SCHEMAS`` both to constrain the model's
output format and to validate what comes back. Later phases refine these models; the
registry and the "one schema per role" rule are the contract.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from slipwright.schemas.job import Job, new_job_id
from slipwright.schemas.profile import Profile, RoleName


class JiraActionType(StrEnum):
    CREATE_ISSUE = "create_issue"
    TRANSITION = "transition"
    COMMENT = "comment"
    LOG_WORK = "log_work"
    LINK_ISSUES = "link_issues"


class JiraAction(BaseModel):
    """One thing an agent wants done in Jira. Fields depend on ``action``."""

    model_config = ConfigDict(extra="forbid")

    action: JiraActionType
    issue: str | None = Field(
        default=None, description="Issue key for transition/comment/log_work."
    )
    issue_type: str | None = Field(
        default=None, description="create_issue: Task, Bug, Subtask, ..."
    )
    summary: str | None = Field(default=None, description="create_issue: title.")
    description: str | None = Field(default=None, description="create_issue: body.")
    parent: str | None = Field(default=None, description="create_issue: parent issue key.")
    to: str | None = Field(default=None, description="transition: target transition/status name.")
    body: str | None = Field(default=None, description="comment: text.")
    minutes: int | None = Field(default=None, ge=1, description="log_work: time spent.")
    note: str | None = Field(default=None, description="log_work: what was done.")
    target: str | None = Field(default=None, description="link_issues: the other issue key.")
    link_type: str = Field(default="Relates", description="link_issues: Relates, Blocks, ...")

    @model_validator(mode="after")
    def _required_fields(self) -> JiraAction:
        need = {
            JiraActionType.CREATE_ISSUE: ("issue_type", "summary"),
            JiraActionType.TRANSITION: ("issue", "to"),
            JiraActionType.COMMENT: ("issue", "body"),
            JiraActionType.LOG_WORK: ("issue", "minutes"),
            JiraActionType.LINK_ISSUES: ("issue", "target"),
        }[self.action]
        missing = [f for f in need if getattr(self, f) in (None, "")]
        if missing:
            raise ValueError(f"{self.action.value} needs {', '.join(missing)}")
        return self

    def idempotency_key(self, role: RoleName, job: Job) -> str:
        payload = json.dumps(
            {
                "role": role.value,
                "phase": job.data.phase_index,
                "qa_stage": job.data.qa_stage,
                "ci": job.data.ci_attempts,
                "attempt": job.data.build_attempts,
                **self.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class RoleOutput(BaseModel):
    """Base for all role outputs. ``extra="forbid"`` keeps the JSON Schema closed."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, description="One-paragraph account of what was done.")
    jira_actions: list[JiraAction] = Field(
        default_factory=list,
        description="Jira actions to perform on the role's behalf (needs the jira permission).",
    )


class PlanPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list, description="Files expected to change.")
    task_id: str | None = Field(
        default=None, description="The backlog task this phase implements (one phase per task)."
    )
    domain: Literal["backend", "web", "mobile", "infra", "docs", "general"] = Field(
        default="general",
        description="Which specialist implements the phase: backend, web, mobile, infra "
        "(DevOps), docs or general (the generic developer).",
    )


class BreakdownTask(BaseModel):
    """One unit of work; maps onto exactly one plan phase."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    phase: int | None = Field(
        default=None, ge=1, description="1-based plan phase; set by the Architect's plan."
    )


class BreakdownStory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    tasks: list[BreakdownTask] = Field(min_length=1)


class BreakdownEpic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    stories: list[BreakdownStory] = Field(min_length=1)


class Breakdown(BaseModel):
    """Epics -> stories -> tasks. Every plan phase is exactly one task."""

    model_config = ConfigDict(extra="forbid")

    epics: list[BreakdownEpic] = Field(min_length=1)

    def tasks(self) -> list[BreakdownTask]:
        return [t for e in self.epics for s in e.stories for t in s.tasks]


class POResult(RoleOutput):
    """The Product Owner's backlog. Task ids are generated when the model omits them."""

    breakdown: Breakdown

    @model_validator(mode="after")
    def _unique_ids(self) -> POResult:
        ids = [t.id for t in self.breakdown.tasks()]
        if len(set(ids)) != len(ids):
            raise ValueError("task ids must be unique")
        return self


class ArchitectResult(RoleOutput):
    """The Architect's answer: how the project is built, what was decided, and the
    phases (one per backlog task; the engine checks the mapping against the backlog)."""

    profile: Profile = Field(description="Build/test/run facts; roles come from the seed.")
    decisions: list[str] = Field(default_factory=list)
    phases: list[PlanPhase] = Field(min_length=1)

    @model_validator(mode="after")
    def _phases_name_tasks(self) -> ArchitectResult:
        seen: set[str] = set()
        for i, phase in enumerate(self.phases, start=1):
            if not phase.task_id:
                raise ValueError(f"phase {i} has no task_id")
            if phase.task_id in seen:
                raise ValueError(f"task {phase.task_id!r} has more than one phase")
            seen.add(phase.task_id)
        return self


class FileChange(BaseModel):
    """Full new contents of one file; ``content: null`` deletes it."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, description="Path relative to the worktree root.")
    content: str | None = Field(description="Complete file contents, or null to delete.")


class DeveloperResult(RoleOutput):
    changes: list[FileChange] = Field(default_factory=list)
    phase_complete: bool = Field(description="Whether the assigned plan phase is finished.")


class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class Violation(BaseModel):
    """One breach of a standards section found in a phase diff (T9.5)."""

    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, description="Heading of the section breached.")
    file: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    severity: Literal["blocking", "advisory"] = "advisory"
    message: str = Field(min_length=1)
    fix: str = Field(default="", description="How to bring the change in line.")


class QAResult(RoleOutput):
    test_cases: list[TestCase] = Field(
        default_factory=list, description="Stage one: proposed test cases."
    )
    changes: list[FileChange] = Field(
        default_factory=list, description="Stage two: test files to write."
    )
    violations: list[Violation] = Field(
        default_factory=list, description="Standards review: breaches found in the diff."
    )


class DevOpsResult(RoleOutput):
    pr_title: str = Field(min_length=1)
    pr_body: str = Field(min_length=1)


class SupervisorResult(RoleOutput):
    """Recommendation at a human gate (T9.8), or the choice on a failed build gate
    (T9.7): ``fix`` (the same specialist tries again), ``replan`` (the architect
    re-plans) or ``ask_human`` (the job waits at the decision gate)."""

    decision: Literal["approve", "reject", "fix", "replan", "ask_human"]
    confidence: float = Field(ge=0.0, le=1.0)
    risk: Literal["low", "medium", "high"]
    reasons: list[str] = Field(default_factory=list)
    feedback: str = Field(default="", description="What to change, when rejecting.")


RESULT_SCHEMAS: dict[RoleName, type[RoleOutput]] = {
    RoleName.PO: POResult,
    RoleName.ARCHITECT: ArchitectResult,
    RoleName.DEVELOPER: DeveloperResult,
    RoleName.BACKEND: DeveloperResult,
    RoleName.WEB_UI: DeveloperResult,
    RoleName.MOBILE_UI: DeveloperResult,
    RoleName.QA: QAResult,
    RoleName.DEVOPS: DevOpsResult,
    RoleName.SUPERVISOR: SupervisorResult,
}


def result_schema_for(role: RoleName) -> type[RoleOutput]:
    return RESULT_SCHEMAS[role]


__all__ = [
    "RESULT_SCHEMAS",
    "ArchitectResult",
    "Breakdown",
    "BreakdownEpic",
    "BreakdownStory",
    "BreakdownTask",
    "POResult",
    "DevOpsResult",
    "DeveloperResult",
    "FileChange",
    "JiraAction",
    "JiraActionType",
    "PlanPhase",
    "QAResult",
    "RoleOutput",
    "SupervisorResult",
    "TestCase",
    "result_schema_for",
]
