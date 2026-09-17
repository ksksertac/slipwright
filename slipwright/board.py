"""Read-only projections over jobs: the epic/story/task board and its statuses.

Nothing here is stored. A task's status is computed from the engine state of the job
that owns it (which phase is next, whether the job failed or finished), so the board can
never disagree with the state machine.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.roles.results import Breakdown
from slipwright.schemas.job import Job, JobState


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


# states before the backlog is approved: nothing is on the board yet
_BACKLOG_PENDING: frozenset[JobState] = frozenset(
    {JobState.CREATED, JobState.BACKLOG, JobState.AWAITING_BACKLOG_APPROVAL}
)


class TaskView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    phase: int | None = None
    domain: str | None = None
    status: TaskStatus
    job_id: str
    files: list[str] = Field(default_factory=list)
    jira_key: str | None = None
    violations: int = Field(default=0, description="Findings of the latest standards review.")
    blocking: int = Field(default=0, description="Of which blocking.")


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
    """True once the backlog is approved: the tree is on the board (and in Jira)."""
    return job.data.backlog is not None and job.state not in _BACKLOG_PENDING


def breakdown_of(job: Job) -> Breakdown | None:
    """The Architect's phase-numbered breakdown when there is a plan, else the PO's."""
    plan = job.data.plan
    raw = (plan or {}).get("breakdown") or job.data.backlog
    return Breakdown.model_validate(raw) if raw else None


def task_status(job: Job, phase: int | None) -> TaskStatus:
    """Status of the task that owns 1-based plan ``phase`` (None: not planned yet)."""
    if not plan_is_active(job) or phase is None:
        return TaskStatus.TODO
    if job.state in (JobState.ARCHITECTURE, JobState.AWAITING_ARCHITECTURE_APPROVAL):
        return TaskStatus.TODO  # the plan is a proposal until approved
    if job.state is JobState.DONE:
        return TaskStatus.DONE
    index = phase - 1
    if (
        job.state in (JobState.REVIEW, JobState.AWAITING_REVIEW_APPROVAL)
        and index == job.data.phase_index - 1
    ):
        return TaskStatus.IN_PROGRESS  # built, but the review is not settled
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


def latest_reviews(job: Job) -> dict[int, dict[str, Any]]:
    """Phase number -> the last standards review recorded for it (T9.5)."""
    latest: dict[int, dict[str, Any]] = {}
    for record in job.data.reviews:
        latest[int(record.get("phase", 0))] = record
    return latest


def job_epics(job: Job) -> list[EpicView]:
    """The job's breakdown with statuses; empty until its plan is approved."""
    if not plan_is_active(job):
        return []
    breakdown = breakdown_of(job)
    if breakdown is None:
        return []
    phases: list[dict[str, Any]] = (job.data.plan or {}).get("phases", [])
    keys: dict[str, str] = job.data.jira_keys
    reviews = latest_reviews(job)
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
                        if t.phase is not None and t.phase - 1 < len(phases)
                        else []
                    ),
                    jira_key=keys.get(t.id),
                    domain=(
                        phases[t.phase - 1].get("domain")
                        if t.phase is not None and t.phase - 1 < len(phases)
                        else None
                    ),
                    violations=len(reviews.get(t.phase or 0, {}).get("violations", [])),
                    blocking=int(reviews.get(t.phase or 0, {}).get("blocking", 0)),
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
