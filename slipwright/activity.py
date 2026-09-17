"""Read-only projections: per-project progress and the itemised activity feed.

Like ``board.py`` this stores nothing. Progress is counted from the board; the activity
feed is every job's history flattened, newest first, each entry classified by which
role or gate produced it so a page can render it without parsing notes itself.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.board import TaskStatus, job_epics
from slipwright.roles.specialists import LABEL, SCOPE, STANDARDS_DOMAIN
from slipwright.schemas.job import APPROVAL_STATES, TERMINAL_STATES, Job, JobState, Transition
from slipwright.schemas.profile import Profile, RoleConfig, RoleName


class ActivityKind(StrEnum):
    STARTED = "started"
    ROLE = "role"  # a role produced something (profile, plan, diff, tests, PR)
    GATE = "gate"  # build gate result
    APPROVAL = "approval"  # human approved / rejected
    INBOX = "inbox"  # steering messages consumed
    JIRA = "jira"  # Jira actions executed or refused
    STANDARDS = "standards"  # sections retrieved into a role's prompt
    CRASH = "crash"  # a phase crashed
    FAILED = "failed"  # the job gave up
    DONE = "done"
    OTHER = "other"


class ActivityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    job_request: str
    project_id: str | None = None
    index: int  # position in ``job.history``; the detail endpoint takes it
    at: datetime
    from_state: JobState
    to_state: JobState
    kind: ActivityKind
    role: RoleName | None = None
    title: str
    has_detail: bool


class JobProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    project_id: str | None = None
    request: str
    state: JobState
    pending_approval: str | None
    current_phase: str
    tasks_done: int
    tasks_total: int
    last_activity: datetime
    pr_url: str | None = None
    recommendation: str | None = None  # the supervisor's decision at the current gate
    confidence: float | None = None
    risk: str | None = None
    auto_approved: bool = False  # the last gate was approved by the supervisor, not undone


class Overview(BaseModel):
    """Dashboard numbers across every project."""

    model_config = ConfigDict(extra="forbid")

    projects: int
    jobs_total: int
    jobs_running: int
    jobs_done: int
    jobs_failed: int
    pending_approvals: int
    tasks_done: int
    tasks_total: int
    waiting: list[JobProgress]
    recent: list[ActivityItem]
    auto_approved: list[JobProgress] = Field(default_factory=list)


class AgentSummary(BaseModel):
    """One agent card: what it is and how much it has worked."""

    model_config = ConfigDict(extra="forbid")

    role: RoleName
    label: str
    scope: str
    standards_domain: str
    invocations: int
    last_used: datetime | None
    model: str
    provider: str | None
    effective_provider: str  # where the role runs right now (the default resolved)
    effective_model: str
    thinking_depth: str
    permissions: list[str]


Router = Callable[[RoleConfig], tuple[str, str]]


def agent_summaries(
    jobs: list[Job], seed: Profile, *, route: Router | None = None
) -> list[AgentSummary]:
    items = [i for job in jobs for i in job_activity(job) if i.kind is ActivityKind.ROLE]
    out: list[AgentSummary] = []
    for role in RoleName:
        mine = [i for i in items if i.role is role]
        cfg = seed.roles[role]
        provider, model = route(cfg) if route else (cfg.provider or "anthropic", cfg.model)
        out.append(
            AgentSummary(
                role=role,
                label=LABEL[role],
                scope=SCOPE[role],
                standards_domain=STANDARDS_DOMAIN[role],
                invocations=len(mine),
                last_used=max((i.at for i in mine), default=None),
                model=cfg.model,
                provider=cfg.provider,
                effective_provider=provider,
                effective_model=model,
                thinking_depth=cfg.thinking_depth.value,
                permissions=[p.value for p in cfg.permissions],
            )
        )
    return out


class ProjectProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    jobs: list[JobProgress]
    jobs_running: int
    jobs_done: int
    jobs_failed: int
    pending_approvals: int
    tasks_done: int
    tasks_total: int
    last_activity: datetime | None
    review_blocking: int = 0  # blocking findings across the project's reviews (T9.6)
    review_advisory: int = 0
    reviews: int = 0


# -- progress ---------------------------------------------------------------------------


def pending_approval(job: Job) -> str | None:
    if job.state is JobState.AWAITING_BACKLOG_APPROVAL:
        return "backlog"
    if job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL:
        return "architecture"
    if job.state is JobState.AWAITING_REVIEW_APPROVAL:
        return "review"
    if job.state is JobState.AWAITING_DECISION:
        return "decision"
    if job.state is JobState.AWAITING_TEST_APPROVAL:
        return "test cases" if job.data.qa_stage == 1 else "written tests"
    return None


def current_phase(job: Job) -> str:
    phases = (job.data.plan or {}).get("phases", [])
    if job.state in (JobState.DEVELOPING, JobState.BUILD_GATE) and phases:
        i = min(job.data.phase_index, len(phases) - 1)
        return f"phase {i + 1}/{len(phases)}: {phases[i].get('goal', '')}"
    if job.state in (JobState.REVIEW, JobState.AWAITING_REVIEW_APPROVAL) and phases:
        i = min(max(job.data.phase_index - 1, 0), len(phases) - 1)
        return f"review of phase {i + 1}/{len(phases)}: {phases[i].get('goal', '')}"
    if job.state is JobState.QA or job.state is JobState.AWAITING_TEST_APPROVAL:
        return f"qa stage {job.data.qa_stage}"
    if job.state is JobState.DEVOPS and job.data.pr_url:
        return f"CI on {job.data.pr_url}"
    if job.history:
        return job.history[-1].note or job.state.value
    return job.state.value


def last_activity(job: Job) -> datetime:
    return job.history[-1].at if job.history else job.created_at


def job_progress(job: Job) -> JobProgress:
    tasks = [t for e in job_epics(job) for s in e.stories for t in s.tasks]
    return JobProgress(
        job_id=job.id,
        project_id=job.project_id,
        request=job.request,
        state=job.state,
        pending_approval=pending_approval(job),
        current_phase=current_phase(job),
        tasks_done=sum(1 for t in tasks if t.status is TaskStatus.DONE),
        tasks_total=len(tasks),
        last_activity=last_activity(job),
        pr_url=job.data.pr_url,
        **supervision_summary(job),
    )


def supervision_summary(job: Job) -> dict[str, Any]:
    record = job.data.supervision or {}
    waiting = job.state in APPROVAL_STATES and record.get("acted") in ("none", None)
    return {
        "recommendation": record.get("decision") if waiting and record else None,
        "confidence": record.get("confidence") if waiting and record else None,
        "risk": record.get("risk") if waiting and record else None,
        "auto_approved": bool(record)
        and record.get("acted") == "auto"
        and not record.get("undone")
        and job.state not in TERMINAL_STATES,
    }


def project_progress(project_id: str, jobs: list[Job]) -> ProjectProgress:
    rows = [job_progress(j) for j in jobs]
    return ProjectProgress(
        project_id=project_id,
        jobs=rows,
        jobs_running=sum(
            1 for j in jobs if j.state not in TERMINAL_STATES and j.state not in APPROVAL_STATES
        ),
        jobs_done=sum(1 for j in jobs if j.state is JobState.DONE),
        jobs_failed=sum(1 for j in jobs if j.state is JobState.FAILED),
        pending_approvals=sum(1 for j in jobs if j.state in APPROVAL_STATES),
        tasks_done=sum(r.tasks_done for r in rows),
        tasks_total=sum(r.tasks_total for r in rows),
        last_activity=max((r.last_activity for r in rows), default=None),
        review_blocking=sum(int(r.get("blocking", 0)) for j in jobs for r in j.data.reviews),
        review_advisory=sum(int(r.get("advisory", 0)) for j in jobs for r in j.data.reviews),
        reviews=sum(len(j.data.reviews) for j in jobs),
    )


def overview(projects: int, jobs: list[Job], *, recent: int = 20) -> Overview:
    rows = [job_progress(j) for j in jobs]
    return Overview(
        projects=projects,
        jobs_total=len(jobs),
        jobs_running=sum(
            1 for j in jobs if j.state not in TERMINAL_STATES and j.state not in APPROVAL_STATES
        ),
        jobs_done=sum(1 for j in jobs if j.state is JobState.DONE),
        jobs_failed=sum(1 for j in jobs if j.state is JobState.FAILED),
        pending_approvals=sum(1 for j in jobs if j.state in APPROVAL_STATES),
        tasks_done=sum(r.tasks_done for r in rows),
        tasks_total=sum(r.tasks_total for r in rows),
        waiting=[r for r in rows if r.pending_approval],
        auto_approved=[r for r in rows if r.auto_approved],
        recent=project_activity(jobs, limit=recent),
    )


# -- activity ---------------------------------------------------------------------------

_INBOX = re.compile(r"^inbox: \d+ message\(s\) consumed by (\w+)")
_JIRA = re.compile(r"^jira(?: \((\w+)\))?:")
_STANDARDS = re.compile(r"^standards \((\w+)(?: phase \d+)?\):")
_ROLE_PREFIX: dict[str, RoleName] = {"PR ": RoleName.DEVOPS, "review phase": RoleName.QA}
for _role in RoleName:
    _ROLE_PREFIX[f"{_role.value}:"] = _role
    _ROLE_PREFIX[f"{_role.value} phase"] = _role


def classify(t: Transition) -> tuple[ActivityKind, RoleName | None]:
    note = t.note or ""
    if (m := _INBOX.match(note)) is not None:
        role = m.group(1)
        return ActivityKind.INBOX, RoleName(role) if role in RoleName.__members__.values() else None
    if (m := _JIRA.match(note)) is not None:
        role = m.group(1)
        return ActivityKind.JIRA, (
            RoleName(role) if role and role in RoleName.__members__.values() else None
        )
    if (m := _STANDARDS.match(note)) is not None:
        role = m.group(1)
        return ActivityKind.STANDARDS, (
            RoleName(role) if role in RoleName.__members__.values() else None
        )
    if note == "job started":
        return ActivityKind.STARTED, None
    if note.startswith("supervisor"):
        return ActivityKind.ROLE, RoleName.SUPERVISOR
    if note.startswith("approved") and " by supervisor" in note:
        return ActivityKind.APPROVAL, RoleName.SUPERVISOR
    if note.startswith(("approved", "rejected", "undo:")):
        return ActivityKind.APPROVAL, None
    if note.startswith("build gate"):
        return ActivityKind.GATE, None
    if t.to_state is JobState.DONE:
        return ActivityKind.DONE, RoleName.DEVOPS
    if t.to_state is JobState.FAILED:
        return (ActivityKind.CRASH if "crashed" in note else ActivityKind.FAILED), _role_of(note)
    role = _role_of(note)
    return (ActivityKind.ROLE if role else ActivityKind.OTHER), role


def _role_of(note: str) -> RoleName | None:
    for prefix, role in _ROLE_PREFIX.items():
        if note.startswith(prefix):
            return role
    for role in RoleName:
        if note.startswith(f"{role.value} failed"):
            return role
    return None


def job_activity(job: Job) -> list[ActivityItem]:
    items: list[ActivityItem] = []
    for index, t in enumerate(job.history):
        kind, role = classify(t)
        items.append(
            ActivityItem(
                job_id=job.id,
                job_request=job.request,
                project_id=job.project_id,
                index=index,
                at=t.at,
                from_state=t.from_state,
                to_state=t.to_state,
                kind=kind,
                role=role,
                title=t.note or f"{t.from_state.value} -> {t.to_state.value}",
                has_detail=bool(t.detail),
            )
        )
    return items


def project_activity(
    jobs: list[Job], *, limit: int | None = None, role: RoleName | None = None
) -> list[ActivityItem]:
    """Every job's history, newest first (stable on ties so one job's order is kept)."""
    items = [i for job in jobs for i in job_activity(job)]
    if role is not None:
        items = [i for i in items if i.role is role]
    items.sort(key=lambda i: (i.at, i.index))
    items.reverse()
    return items[:limit] if limit else items


__all__ = [
    "ActivityItem",
    "ActivityKind",
    "AgentSummary",
    "agent_summaries",
    "JobProgress",
    "Overview",
    "overview",
    "ProjectProgress",
    "classify",
    "current_phase",
    "job_activity",
    "job_progress",
    "pending_approval",
    "project_activity",
    "project_progress",
]
