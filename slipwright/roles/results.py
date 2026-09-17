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


class AnalystResult(RoleOutput):
    profile: Profile = Field(description="Project profile inferred from the worktree.")


class PlanPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list, description="Files expected to change.")


class BreakdownTask(BaseModel):
    """One unit of work; maps onto exactly one plan phase."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    phase: int = Field(ge=1, description="1-based index into PlannerResult.phases.")


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


class PlannerResult(RoleOutput):
    phases: list[PlanPhase] = Field(min_length=1)
    breakdown: Breakdown | None = Field(
        default=None,
        description="Epics/stories/tasks over the phases; generated when omitted.",
    )

    @model_validator(mode="after")
    def _breakdown_covers_phases(self) -> PlannerResult:
        if self.breakdown is None:
            return self
        seen: dict[int, str] = {}
        for task in self.breakdown.tasks():
            if task.phase > len(self.phases):
                raise ValueError(
                    f"task {task.title!r} references phase {task.phase} "
                    f"but the plan has {len(self.phases)}"
                )
            if task.phase in seen:
                raise ValueError(
                    f"phase {task.phase} is referenced by both {seen[task.phase]!r} "
                    f"and {task.title!r}"
                )
            seen[task.phase] = task.title
        missing = [i + 1 for i in range(len(self.phases)) if i + 1 not in seen]
        if missing:
            raise ValueError(f"no task references phase(s) {missing}")
        return self


def default_breakdown(request: str, phases: list[PlanPhase]) -> Breakdown:
    """One epic, one story, one task per phase: what a plan without a breakdown means."""
    title = request.strip().splitlines()[0][:120] if request.strip() else "Request"
    return Breakdown(
        epics=[
            BreakdownEpic(
                title=title,
                stories=[
                    BreakdownStory(
                        title=title,
                        tasks=[
                            BreakdownTask(title=phase.goal, phase=i + 1)
                            for i, phase in enumerate(phases)
                        ],
                    )
                ],
            )
        ]
    )


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


class QAResult(RoleOutput):
    test_cases: list[TestCase] = Field(
        default_factory=list, description="Stage one: proposed test cases."
    )
    changes: list[FileChange] = Field(
        default_factory=list, description="Stage two: test files to write."
    )


class DevOpsResult(RoleOutput):
    pr_title: str = Field(min_length=1)
    pr_body: str = Field(min_length=1)


RESULT_SCHEMAS: dict[RoleName, type[RoleOutput]] = {
    RoleName.ANALYST: AnalystResult,
    RoleName.PLANNER: PlannerResult,
    RoleName.DEVELOPER: DeveloperResult,
    RoleName.QA: QAResult,
    RoleName.DEVOPS: DevOpsResult,
}


def result_schema_for(role: RoleName) -> type[RoleOutput]:
    return RESULT_SCHEMAS[role]


__all__ = [
    "RESULT_SCHEMAS",
    "AnalystResult",
    "Breakdown",
    "BreakdownEpic",
    "BreakdownStory",
    "BreakdownTask",
    "default_breakdown",
    "DevOpsResult",
    "DeveloperResult",
    "FileChange",
    "JiraAction",
    "JiraActionType",
    "PlanPhase",
    "PlannerResult",
    "QAResult",
    "RoleOutput",
    "TestCase",
    "result_schema_for",
]
