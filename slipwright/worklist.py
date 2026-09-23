"""What a development will do, grouped by the agent that will do it.

The list is built from what the Product Owner and the Architect have already produced —
the backlog and the phases — plus the steps every development ends with, so QA and DevOps
appear before anything is built rather than as a surprise later. Each item says which role
owns it and whether the person can edit it here; the editors that already exist (backlog,
plan) do the editing, so this module only ever reads.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.board import job_epics
from slipwright.roles.specialists import LABEL, specialist_for
from slipwright.schemas.job import Job
from slipwright.schemas.profile import RoleName


class WorkItem(BaseModel):
    """One line of the work list."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    detail: str = ""
    # backlog | phase | step: what the person edits it through, if anything
    kind: str
    editable: bool = False
    domain: str | None = None
    phase: int | None = None


class WorkGroup(BaseModel):
    """One agent's part of the list."""

    model_config = ConfigDict(extra="forbid")

    role: RoleName
    label: str
    summary: str  # what this agent is about to do, in one line
    items: list[WorkItem] = Field(default_factory=list)


class WorkList(BaseModel):
    """The whole list, in the order the work happens."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: str
    editable: bool  # the development has not started yet: the list can still be changed
    plan_summary: str = ""
    groups: list[WorkGroup] = Field(default_factory=list)
    tasks: int = 0
    phases: int = 0


# the steps that always follow the phases, whatever the plan says
_TAIL: tuple[tuple[RoleName, str, tuple[tuple[str, str], ...]], ...] = (
    (
        RoleName.QA,
        "Proposes the test cases, then writes the tests you approve",
        (
            ("qa:cases", "Propose the test cases for the approved backlog"),
            ("qa:tests", "Write the tests that cover the approved cases"),
        ),
    ),
    (
        RoleName.DEVOPS,
        "Takes the finished branch to where the code lives",
        (
            ("devops:pr", "Push the branch and open a pull request"),
            ("devops:ci", "Watch the checks and fix what they report"),
        ),
    ),
)


def work_list(job: Job) -> WorkList:
    """The list as it stands: what each agent is about to do."""
    plan: dict[str, Any] = job.data.plan or {}
    phases: list[dict[str, Any]] = list(plan.get("phases") or [])
    editable = job.state.value in ("awaiting_backlog_approval", "awaiting_architecture_approval")
    out = WorkList(
        job_id=job.id,
        state=job.state.value,
        editable=editable,
        plan_summary=str(plan.get("summary") or ""),
        phases=len(phases),
    )

    # the Product Owner: the backlog it wrote, one line per task under its story
    po_items: list[WorkItem] = []
    for epic in job_epics(job):
        for story in epic.stories:
            for task in story.tasks:
                po_items.append(
                    WorkItem(
                        id=task.id,
                        title=task.title,
                        detail=f"{epic.title} › {story.title}",
                        kind="backlog",
                        editable=editable,
                        phase=task.phase,
                    )
                )
    out.tasks = len(po_items)
    if po_items:
        out.groups.append(
            WorkGroup(
                role=RoleName.PO,
                label=LABEL[RoleName.PO],
                summary="Turned the request into epics, stories and tasks",
                items=po_items,
            )
        )

    # the Architect: the decisions it took, then one phase per task for each specialist
    decisions = [str(d) for d in (plan.get("decisions") or [])]
    if decisions or phases:
        out.groups.append(
            WorkGroup(
                role=RoleName.ARCHITECT,
                label=LABEL[RoleName.ARCHITECT],
                summary="Decided how it is built, tested and run",
                items=[
                    WorkItem(id=f"decision:{i}", title=d, kind="step")
                    for i, d in enumerate(decisions)
                ],
            )
        )

    by_role: dict[RoleName, list[WorkItem]] = {}
    for i, phase in enumerate(phases):
        role = specialist_for(phase.get("domain"))
        by_role.setdefault(role, []).append(
            WorkItem(
                id=f"phase:{i}",
                title=str(phase.get("title") or f"phase {i + 1}"),
                detail=str(phase.get("goal") or phase.get("summary") or ""),
                kind="phase",
                editable=editable,
                domain=str(phase.get("domain") or "") or None,
                phase=i + 1,
            )
        )
    for role, items in by_role.items():
        out.groups.append(
            WorkGroup(
                role=role,
                label=LABEL[role],
                summary=f"{len(items)} phase(s), each behind the build gate",
                items=items,
            )
        )

    for role, summary, steps in _TAIL:
        out.groups.append(
            WorkGroup(
                role=role,
                label=LABEL[role],
                summary=summary,
                items=[WorkItem(id=key, title=title, kind="step") for key, title in steps],
            )
        )
    return out


__all__ = ["WorkGroup", "WorkItem", "WorkList", "work_list"]
