"""Read-only projections over jobs: the epic/story/task board and its statuses.

Nothing here is stored. A task's status is computed from the engine state of the job
that owns it (which phase is next, whether the job failed or finished), so the board can
never disagree with the state machine.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.roles.results import Breakdown, PlanPhase, default_breakdown
from slipwright.schemas.job import Job, JobState


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


# states in which ``job.data.plan`` is the plan being executed, not a proposal
_PLAN_PENDING: frozenset[JobState] = frozenset(
    {
        JobState.CREATED,
        JobState.ANALYZING,
        JobState.AWAITING_PROFILE_APPROVAL,
        JobState.PLANNING,
        JobState.AWAITING_PLAN_APPROVAL,
    }
)


class TaskView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    phase: int
    status: TaskStatus
    job_id: str
    files: list[str] = Field(default_factory=list)
    jira_key: str | None = None


class StoryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    status: TaskStatus
    job_id: str
    tasks: list[TaskView]
    jira_key: str | None = None


class EpicView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    status: TaskStatus
    job_id: str
    job_request: str
    job_state: JobState
    stories: list[StoryView]
    jira_key: str | None = None


class Board(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    epics: list[EpicView]
    tasks_total: int
    tasks_done: int


def plan_is_active(job: Job) -> bool:
    """True once a plan has been approved (or the job ended after approving one)."""
    return job.data.plan is not None and job.state not in _PLAN_PENDING


def breakdown_of(job: Job) -> Breakdown | None:
    """The job's breakdown, generating the default one for plans that carry none."""
    plan = job.data.plan
    if not plan:
        return None
    phases = [PlanPhase.model_validate(p) for p in plan.get("phases", [])]
    if not phases:
        return None
    raw = plan.get("breakdown")
    if raw:
        return Breakdown.model_validate(raw)
    return default_breakdown(job.request, phases)


def task_status(job: Job, phase: int) -> TaskStatus:
    """Status of the task that owns 1-based plan ``phase``."""
    if not plan_is_active(job):
        return TaskStatus.TODO
    if job.state is JobState.DONE:
        return TaskStatus.DONE
    index = phase - 1
    if index < job.data.phase_index:
        return TaskStatus.DONE
    if index == job.data.phase_index:
        if job.state is JobState.FAILED:
            return TaskStatus.FAILED
        if job.state in (JobState.DEVELOPING, JobState.BUILD_GATE):
            return TaskStatus.IN_PROGRESS
    return TaskStatus.TODO


def rollup(statuses: list[TaskStatus]) -> TaskStatus:
    if not statuses:
        return TaskStatus.TODO
    if any(s is TaskStatus.FAILED for s in statuses):
        return TaskStatus.FAILED
    if all(s is TaskStatus.DONE for s in statuses):
        return TaskStatus.DONE
    if any(s in (TaskStatus.IN_PROGRESS, TaskStatus.DONE) for s in statuses):
        return TaskStatus.IN_PROGRESS
    return TaskStatus.TODO


def job_epics(job: Job) -> list[EpicView]:
    """The job's breakdown with statuses; empty until its plan is approved."""
    if not plan_is_active(job):
        return []
    breakdown = breakdown_of(job)
    if breakdown is None:
        return []
    phases: list[dict[str, Any]] = (job.data.plan or {}).get("phases", [])
    keys: dict[str, str] = job.data.jira_keys
    epics: list[EpicView] = []
    for epic in breakdown.epics:
        stories: list[StoryView] = []
        for story in epic.stories:
            tasks = [
                TaskView(
                    id=t.id,
                    title=t.title,
                    description=t.description,
                    phase=t.phase,
                    status=task_status(job, t.phase),
                    job_id=job.id,
                    files=(
                        list(phases[t.phase - 1].get("files", []))
                        if t.phase - 1 < len(phases)
                        else []
                    ),
                    jira_key=keys.get(t.id),
                )
                for t in story.tasks
            ]
            stories.append(
                StoryView(
                    id=story.id,
                    title=story.title,
                    description=story.description,
                    status=rollup([t.status for t in tasks]),
                    job_id=job.id,
                    tasks=tasks,
                    jira_key=keys.get(story.id),
                )
            )
        epics.append(
            EpicView(
                id=epic.id,
                title=epic.title,
                description=epic.description,
                status=rollup([s.status for s in stories]),
                job_id=job.id,
                job_request=job.request,
                job_state=job.state,
                stories=stories,
                jira_key=keys.get(epic.id),
            )
        )
    return epics


def project_board(project_id: str, jobs: list[Job]) -> Board:
    epics = [e for job in jobs for e in job_epics(job)]
    tasks = [t for e in epics for s in e.stories for t in s.tasks]
    return Board(
        project_id=project_id,
        epics=epics,
        tasks_total=len(tasks),
        tasks_done=sum(1 for t in tasks if t.status is TaskStatus.DONE),
    )


__all__ = [
    "Board",
    "EpicView",
    "StoryView",
    "TaskStatus",
    "TaskView",
    "breakdown_of",
    "job_epics",
    "plan_is_active",
    "project_board",
    "rollup",
    "task_status",
]
