"""What one pipeline step actually did, item by item (T9.10).

The lane cards say *that* a step ran; this says *what came out of it* — the epics the
Product Owner wrote and whether each reached Jira, the decisions the Architect settled
on, the files a phase was supposed to touch and what the build gate said about them, the
test cases you approved, the branch and pull request DevOps produced. Every item carries
when it happened and, for anything you had to sign off, when it was approved.

Like ``pipeline`` and ``board`` this is a pure projection over the job's persisted state
and history: nothing here is stored, so it is exact after a restart. Labels are fixed
English strings the web UI translates; agent-written content (a task title, a goal, a
decision) is passed through in the language the project asked the agents to write in.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.board import TaskStatus, breakdown_of, plan_is_active, task_status
from slipwright.pipeline import StepCard, StepStatus, lane_for
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import RoleName


class ItemStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Badge(BaseModel):
    """A short mark on an item: a Jira key, a domain, a file count. ``label`` is a fixed
    English string the UI translates; ``value`` is content and is shown as it is."""

    model_config = ConfigDict(extra="forbid")

    label: str = ""
    value: str = ""
    tone: str = "idle"  # idle | ok | bad | wait | work


class StepItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str  # epic | story | task | decision | fact | phase | file | case | check | ...
    title: str
    detail: str = ""
    status: ItemStatus = ItemStatus.DONE
    at: datetime | None = Field(default=None, description="When this item was produced.")
    approved_at: datetime | None = None
    badges: list[Badge] = Field(default_factory=list)
    children: list[StepItem] = Field(default_factory=list)


class StepGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str  # fixed English, translated by the UI
    note: str = ""  # fixed English; one line saying what the group is
    empty: str = ""  # fixed English; shown instead of an empty list
    items: list[StepItem] = Field(default_factory=list)


class StepDetail(BaseModel):
    """One step of one development, with everything it produced."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    key: str
    label: str
    role: RoleName | None = None
    gate: bool = False
    status: StepStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_s: float | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None  # "you" | "supervisor"
    summary: str = Field(default="", description="The role's own account, as it wrote it.")
    groups: list[StepGroup] = Field(default_factory=list)
    outputs: list[int] = Field(default_factory=list, description="History indexes, as on the card.")


_TASK_TO_ITEM = {
    TaskStatus.TODO: ItemStatus.TODO,
    TaskStatus.IN_PROGRESS: ItemStatus.IN_PROGRESS,
    TaskStatus.DONE: ItemStatus.DONE,
    TaskStatus.FAILED: ItemStatus.FAILED,
}
_DIFF_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)
_PHASE_NOTE = re.compile(r"^(\w+) phase (\d+)/(\d+)")
_GATE_PASSED = re.compile(r"^build gate passed for phase (\d+)/")
_GATE_FAILED = re.compile(r"^build gate failed (?:on phase|\d+ times on phase) (\d+)")
# the standards note is the first thing written for a phase, so it marks where one opens
_PHASE_STANDARDS = re.compile(r"^standards \(\w+ phase (\d+)\)")
# a retry, a truncated answer or a crash names the role and the attempt, never the phase
_ROLE_ATTEMPT = re.compile(r"^\w+ attempt \d+[: ]")


def _summary_of(job: Job, card: StepCard) -> str:
    """The role's own paragraph. The engine writes it into the output transition's detail
    as JSON for the two planning steps; elsewhere the note carries it after the colon."""
    for index in card.outputs:
        if index >= len(job.history):
            continue
        entry = job.history[index]
        if entry.detail and entry.detail.lstrip().startswith("{"):
            try:
                loaded = json.loads(entry.detail)
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict) and loaded.get("summary"):
                return str(loaded["summary"])
        note = entry.note or ""
        if ": " in note and not note.startswith(("jira", "standards", "approved", "rejected")):
            return note.split(": ", 1)[1]
    return ""


def _approval(job: Job, card: StepCard) -> tuple[datetime | None, str | None]:
    """When this gate was signed off and by whom; nothing for a step that is not a gate
    or one that is still waiting."""
    if not card.gate or card.status is not StepStatus.DONE or not card.outputs:
        return None, None
    opened = card.outputs[0]
    if opened >= len(job.history):
        return None, None
    state = job.history[opened].to_state
    for entry in job.history[opened + 1 :]:
        if entry.from_state is state and (entry.note or "").startswith("approved"):
            return entry.at, ("supervisor" if " by supervisor" in (entry.note or "") else "you")
    return None, None


def _files_in(diff: str | None) -> list[str]:
    """Paths of a unified diff, in the order they appear."""
    if not diff:
        return []
    seen: list[str] = []
    for _, after in _DIFF_FILE.findall(diff):
        if after not in seen:
            seen.append(after)
    return seen


def _jira_badge(job: Job, item_id: str) -> Badge:
    key = job.data.jira_keys.get(item_id)
    if key:
        status = job.data.jira_status.get(item_id, "")
        return Badge(label="Jira", value=f"{key}{f' · {status}' if status else ''}", tone="ok")
    return Badge(label="not in Jira", tone="idle")


def _backlog_tree(job: Job) -> list[StepItem]:
    """The breakdown as epic → story → task, each task carrying the status the board
    computes for it and whether it reached Jira."""
    breakdown = breakdown_of(job)
    if breakdown is None:
        return []
    planned = plan_is_active(job)
    epics: list[StepItem] = []
    for epic in breakdown.epics:
        stories: list[StepItem] = []
        for story in epic.stories:
            tasks = [
                StepItem(
                    kind="task",
                    title=task.title,
                    detail=task.description,
                    status=(
                        _TASK_TO_ITEM[task_status(job, task.phase)] if planned else ItemStatus.TODO
                    ),
                    badges=[
                        _jira_badge(job, task.id),
                        *(
                            [Badge(label="phase", value=str(task.phase), tone="work")]
                            if task.phase
                            else []
                        ),
                    ],
                )
                for task in story.tasks
            ]
            stories.append(
                StepItem(
                    kind="story",
                    title=story.title,
                    detail=story.description,
                    status=_rollup([t.status for t in tasks]),
                    badges=[_jira_badge(job, story.id)],
                    children=tasks,
                )
            )
        epics.append(
            StepItem(
                kind="epic",
                title=epic.title,
                detail=epic.description,
                status=_rollup([s.status for s in stories]),
                badges=[_jira_badge(job, epic.id)],
                children=stories,
            )
        )
    return epics


def _rollup(statuses: list[ItemStatus]) -> ItemStatus:
    if not statuses:
        return ItemStatus.TODO
    if any(s is ItemStatus.FAILED for s in statuses):
        return ItemStatus.FAILED
    if all(s is ItemStatus.DONE for s in statuses):
        return ItemStatus.DONE
    if any(s in (ItemStatus.IN_PROGRESS, ItemStatus.DONE) for s in statuses):
        return ItemStatus.IN_PROGRESS
    return ItemStatus.TODO


def _jira_group(job: Job, *, only: str | None = None) -> StepGroup:
    """What the agents asked Jira to do and how it went: one item per recorded sweep,
    plus the last error while one is outstanding."""
    items: list[StepItem] = []
    for entry in job.history:
        note = entry.note or ""
        if not note.startswith("jira"):
            continue
        if only is not None and f"({only})" not in note:
            continue
        # queued means Jira was unreachable and the action is still owed, not lost
        status = (
            ItemStatus.FAILED
            if "refused" in note
            else ItemStatus.IN_PROGRESS
            if "queued" in note
            else ItemStatus.DONE
        )
        items.append(
            StepItem(
                kind="jira",
                title=note,
                detail=entry.detail or "",
                status=status,
                at=entry.at,
            )
        )
    if job.data.jira_last_error:
        items.append(
            StepItem(
                kind="jira",
                title="the last Jira sync failed",
                detail=job.data.jira_last_error,
                status=ItemStatus.FAILED,
            )
        )
    return StepGroup(
        key="jira",
        label="Jira",
        note="What was mirrored to Jira, and what is still waiting.",
        empty="Nothing was sent to Jira for this step.",
        items=items,
    )


def _jira_mirror_group(job: Job) -> StepGroup:
    """Whether the backlog itself reached Jira. The per-item badges say which issue each
    epic, story and task became; this says how far the mirror got as a whole, which is
    what you look for when a key is missing."""
    breakdown = breakdown_of(job)
    ids: list[str] = []
    if breakdown is not None:
        for epic in breakdown.epics:
            ids.append(epic.id)
            for story in epic.stories:
                ids.append(story.id)
                ids.extend(task.id for task in story.tasks)
    mirrored = sum(1 for i in ids if i in job.data.jira_keys)
    items = [
        StepItem(
            kind="jira",
            title="Mirrored to Jira",
            detail=f"{mirrored}/{len(ids)}",
            status=(
                ItemStatus.DONE
                if ids and mirrored == len(ids)
                else ItemStatus.IN_PROGRESS
                if mirrored
                else ItemStatus.TODO
            ),
        )
    ]
    if job.data.jira_sprint_id is not None:
        items.append(StepItem(kind="jira", title="Sprint", detail=str(job.data.jira_sprint_id)))
    group = _jira_group(job, only="po")
    return StepGroup(
        key="jira",
        label="Jira",
        note="Where the backlog ended up: one issue per epic, story and task.",
        items=items + group.items,
    )


def _history_group(
    job: Job, indexes: list[int], *, key: str, label: str, note: str = ""
) -> StepGroup:
    """Raw history entries as items: the record of what the engine did, in order."""
    items = [
        StepItem(
            kind="event",
            title=job.history[i].note or f"{job.history[i].from_state} → {job.history[i].to_state}",
            detail=job.history[i].detail or "",
            status=(
                ItemStatus.FAILED if job.history[i].to_state is JobState.FAILED else ItemStatus.DONE
            ),
            at=job.history[i].at,
        )
        for i in sorted(set(indexes))
        if i < len(job.history)
    ]
    return StepGroup(key=key, label=label, note=note, empty="Nothing recorded yet.", items=items)


# -- per-step groups ---------------------------------------------------------------------


def _backlog_groups(job: Job) -> list[StepGroup]:
    return [
        StepGroup(
            key="breakdown",
            label="Epics, stories and tasks",
            note="Every epic opens onto its stories, and every story onto its tasks.",
            empty="The Product Owner has not written the backlog yet.",
            items=_backlog_tree(job),
        ),
        _jira_mirror_group(job),
    ]


def _architecture_groups(job: Job) -> list[StepGroup]:
    plan = job.data.plan or {}
    decisions = [
        StepItem(kind="decision", title=str(d)) for d in plan.get("decisions", []) if str(d).strip()
    ]
    profile = job.profile
    facts: list[StepItem] = []
    if profile is not None:
        for label, value in (
            ("Language", profile.language),
            ("Package manager", profile.package_manager),
            ("Build", profile.build_cmd),
            ("Tests", profile.test_cmd),
            ("Run", profile.run_cmd),
        ):
            if value:
                facts.append(StepItem(kind="fact", title=label, detail=str(value)))
    phases: list[StepItem] = []
    titles = _task_titles(job)
    for number, phase in enumerate(plan.get("phases", []), start=1):
        files = list(phase.get("files", []))
        phases.append(
            StepItem(
                kind="phase",
                title=str(phase.get("goal", "")),
                detail=titles.get(str(phase.get("task_id")), ""),
                status=(
                    _TASK_TO_ITEM[task_status(job, number)]
                    if plan_is_active(job)
                    else ItemStatus.TODO
                ),
                badges=[
                    Badge(label="phase", value=str(number), tone="work"),
                    Badge(label="", value=str(phase.get("domain") or "general")),
                    *([Badge(label="files", value=str(len(files)))] if files else []),
                ],
                children=[StepItem(kind="file", title=f) for f in files],
            )
        )
    return [
        StepGroup(
            key="decisions",
            label="Decisions",
            note="What the Architect settled on, and why the plan looks the way it does.",
            empty="The Architect recorded no separate decisions.",
            items=decisions,
        ),
        StepGroup(
            key="setup",
            label="How it is built, tested and run",
            empty="No build facts were proposed.",
            items=facts,
        ),
        StepGroup(
            key="phases",
            label="Phases",
            note="One phase per backlog task, in the order they are built.",
            empty="No phases were planned.",
            items=phases,
        ),
        _jira_group(job, only="architect"),
    ]


def _task_titles(job: Job) -> dict[str, str]:
    breakdown = breakdown_of(job)
    if breakdown is None:
        return {}
    return {t.id: t.title for t in breakdown.tasks()}


def _phase_groups(job: Job, number: int) -> list[StepGroup]:
    plan = job.data.plan or {}
    phases: list[dict[str, Any]] = list(plan.get("phases", []))
    if number - 1 >= len(phases):
        return []
    phase = phases[number - 1]
    breakdown = breakdown_of(job)
    task = next(
        (t for t in (breakdown.tasks() if breakdown else []) if t.id == phase.get("task_id")),
        None,
    )
    assignment = [
        StepItem(
            kind="goal",
            title=str(phase.get("goal", "")),
            detail=task.description if task else "",
            status=(
                _TASK_TO_ITEM[task_status(job, number)] if plan_is_active(job) else ItemStatus.TODO
            ),
            badges=[
                Badge(label="", value=str(phase.get("domain") or "general")),
                *([_jira_badge(job, task.id)] if task else []),
            ],
        )
    ]
    written: list[StepItem] = []
    events: list[int] = []
    open_phase = 0  # the phase the engine was on, for the notes that name none themselves
    for index, entry in enumerate(job.history):
        note = entry.note or ""
        if match := _PHASE_NOTE.match(note):
            open_phase = int(match.group(2))
            if open_phase == number:
                events.append(index)
                for path in _files_in(entry.detail):
                    if all(w.title != path for w in written):
                        written.append(StepItem(kind="file", title=path, at=entry.at))
            continue
        if m := (_GATE_PASSED.match(note) or _GATE_FAILED.match(note)):
            open_phase = int(m.group(1))
            if open_phase == number:
                events.append(index)
            continue
        if m := _PHASE_STANDARDS.match(note):
            open_phase = int(m.group(1))  # opens the phase; the note itself is bookkeeping
            continue
        # a retried call, an answer cut off at the output limit and the failure that ended
        # the job all name the role and not the phase -- without them the panel shows a
        # phase that stopped and never says why. They belong to the phase that was open.
        if open_phase == number and (
            _ROLE_ATTEMPT.match(note)
            or (entry.to_state is JobState.FAILED and entry.from_state is not JobState.FAILED)
        ):
            events.append(index)
    # a planned file the diff never touched is worth seeing: the phase went another way
    touched = {w.title for w in written}
    planned_files = [
        StepItem(
            kind="file",
            title=f,
            status=ItemStatus.DONE
            if f in touched
            else ItemStatus.SKIPPED
            if written
            else ItemStatus.TODO,
        )
        for f in phase.get("files", [])
    ]
    review = next(
        (r for r in reversed(job.data.reviews) if int(r.get("phase", 0)) == number),
        None,
    )
    violations = [
        StepItem(
            kind="violation",
            title=str(v.get("message", "")),
            detail=str(v.get("fix", "")),
            status=(
                ItemStatus.FAILED if v.get("severity") == "blocking" else ItemStatus.IN_PROGRESS
            ),
            badges=[
                Badge(label="", value=str(v.get("section", "")), tone="idle"),
                Badge(
                    label="",
                    value=f"{v.get('file', '')}{f':{v["line"]}' if v.get('line') else ''}",
                ),
                Badge(
                    label="",
                    value=str(v.get("severity", "advisory")),
                    tone="bad" if v.get("severity") == "blocking" else "wait",
                ),
            ],
        )
        for v in (review or {}).get("violations", [])
    ]
    return [
        StepGroup(
            key="assignment",
            label="What this phase was asked to do",
            items=assignment,
        ),
        StepGroup(
            key="files",
            label="Files",
            note="Planned by the Architect, then what the diff actually touched.",
            empty="No files were named for this phase.",
            items=[
                *(
                    [
                        StepItem(
                            kind="group",
                            title="planned",
                            status=_rollup([f.status for f in planned_files]),
                            badges=[Badge(label="", value=str(len(planned_files)))],
                            children=planned_files,
                        )
                    ]
                    if planned_files
                    else []
                ),
                *(
                    [
                        StepItem(
                            kind="group",
                            title="changed",
                            badges=[Badge(label="", value=str(len(written)))],
                            children=written,
                        )
                    ]
                    if written
                    else []
                ),
            ],
        ),
        _history_group(
            job,
            events,
            key="events",
            label="What happened",
            note="The phase's own run and every build gate it went through.",
        ),
        StepGroup(
            key="review",
            label="Standards review",
            note="What QA found when it read this phase's diff against the standards.",
            empty="No standards review was recorded for this phase.",
            items=violations,
        ),
    ]


def _qa_cases_groups(job: Job) -> list[StepGroup]:
    approved = any(
        (t.note or "").startswith("approved") and t.from_state is JobState.AWAITING_TEST_APPROVAL
        for t in job.history
    )
    cases = [
        StepItem(
            kind="case",
            title=str(case.get("name", "")),
            detail=str(case.get("description", "")),
            status=ItemStatus.DONE if approved else ItemStatus.TODO,
        )
        for case in job.data.test_cases
    ]
    return [
        StepGroup(
            key="cases",
            label="Test cases",
            note="The scenarios QA proposed; the tests are written against exactly these.",
            empty="QA proposed no test cases.",
            items=cases,
        )
    ]


def _qa_tests_groups(job: Job, card: StepCard) -> list[StepGroup]:
    files: list[StepItem] = []
    runs: list[int] = []
    for index in card.outputs:
        if index >= len(job.history):
            continue
        entry = job.history[index]
        runs.append(index)
        for path in _files_in(entry.detail):
            if all(f.title != path for f in files):
                files.append(StepItem(kind="file", title=path, at=entry.at))
    return [
        StepGroup(
            key="test_files",
            label="Test files written",
            empty="QA wrote no new test files: the approved cases were already covered.",
            items=files,
        ),
        _history_group(
            job,
            runs,
            key="run",
            label="The run",
            note="What the build and test commands said.",
        ),
        _jira_group(job, only="qa"),
    ]


def _devops_groups(job: Job, card: StepCard) -> list[StepGroup]:
    pushed = job.data.pr_url is not None
    failed_note = next(
        (
            t.note
            for t in reversed(job.history)
            if (t.note or "").startswith("devops:") or "nothing was pushed" in (t.note or "")
        ),
        None,
    )
    delivery = [
        StepItem(kind="fact", title="Branch", detail=job.branch, status=ItemStatus.DONE),
        StepItem(
            kind="fact",
            title="Pull request",
            detail=job.data.pr_url or (failed_note or "not opened"),
            status=ItemStatus.DONE if pushed else ItemStatus.FAILED,
            badges=[
                Badge(label="pushed" if pushed else "not pushed", tone="ok" if pushed else "bad")
            ],
        ),
    ]
    if job.data.ci_attempts:
        delivery.append(
            StepItem(
                kind="fact",
                title="CI fix rounds",
                detail=str(job.data.ci_attempts),
                status=ItemStatus.IN_PROGRESS,
            )
        )
    return [
        StepGroup(
            key="delivery",
            label="Delivery",
            note="Where the work ended up: the branch, the pull request and its checks.",
            items=delivery,
        ),
        _history_group(
            job,
            list(card.outputs),
            key="events",
            label="What happened",
        ),
        _jira_group(job, only="devops"),
    ]


def _deploy_groups(job: Job) -> list[StepGroup]:
    """What DevOps proposes to deploy, and which of those files exist on the branch."""
    plan = job.data.deploy or {}
    target = str(plan.get("target") or "")
    written = set(job.data.deploy_written)
    facts = [
        StepItem(
            kind="fact",
            title="Target",
            detail=target or "not decided yet",
            status=ItemStatus.DONE if target else ItemStatus.TODO,
            badges=[Badge(label="cloud", value=target, tone="ok" if target != "none" else "idle")]
            if target
            else [],
        )
    ]
    services = [str(x) for x in plan.get("services", [])]
    if services:
        facts.append(
            StepItem(kind="fact", title="Services", detail=", ".join(services)),
        )
    scripts = [
        StepItem(
            kind="file",
            title=str(sc.get("path", "")),
            detail=str(sc.get("purpose", "")),
            status=ItemStatus.DONE if str(sc.get("path")) in written else ItemStatus.TODO,
            badges=[Badge(label="written", tone="ok")] if str(sc.get("path")) in written else [],
        )
        for sc in plan.get("scripts", [])
    ]
    notes = [
        StepItem(kind="check", title=str(n), status=ItemStatus.TODO) for n in plan.get("notes", [])
    ]
    return [
        StepGroup(key="deployment", label="Deployment", items=facts),
        StepGroup(
            key="scripts",
            label="Scripts",
            items=scripts,
            empty="Nothing to deploy for this development.",
        ),
        StepGroup(key="notes", label="What you have to supply", items=notes),
    ]


def _gate_groups(job: Job, card: StepCard) -> list[StepGroup]:
    """A gate shows the material it is about, then the decision itself."""
    material: list[StepGroup] = []
    if card.key == "backlog_gate":
        material = [_backlog_groups(job)[0]]
    elif card.key == "architecture_gate":
        material = _architecture_groups(job)[:3]
    elif card.key.startswith("test_gate:1"):
        material = _qa_cases_groups(job)
    elif card.key == "deploy_gate":
        material = _deploy_groups(job)
    elif card.key.startswith("review_gate:") and card.phase:
        material = [_phase_groups(job, card.phase)[-1]]
    decisions: list[StepItem] = []
    if card.outputs:
        opened = card.outputs[0]
        state = job.history[opened].to_state if opened < len(job.history) else None
        for entry in job.history[opened + 1 :]:
            note = entry.note or ""
            if entry.from_state is state and note.startswith(("approved", "rejected")):
                decisions.append(
                    StepItem(
                        kind="decision",
                        title=note,
                        status=(
                            ItemStatus.DONE if note.startswith("approved") else ItemStatus.FAILED
                        ),
                        at=entry.at,
                    )
                )
                break
    supervision = job.data.supervision or {}
    if card.status is StepStatus.WAITING and supervision.get("acted") == "none":
        reasons = "; ".join(str(r) for r in supervision.get("reasons", []))
        decisions.append(
            StepItem(
                kind="advice",
                title="The supervisor's advice",
                detail=reasons or str(supervision.get("feedback", "")),
                status=ItemStatus.IN_PROGRESS,
                badges=[
                    Badge(label="recommends", value=str(supervision.get("decision", ""))),
                    Badge(label="confidence", value=f"{supervision.get('confidence', 0):.2f}"),
                    Badge(label="risk", value=str(supervision.get("risk", ""))),
                ],
            )
        )
    return [
        *material,
        StepGroup(
            key="decision",
            label="The decision",
            empty="Nobody has decided yet.",
            items=decisions,
        ),
    ]


def _done_groups(job: Job) -> list[StepGroup]:
    items = [
        StepItem(kind="fact", title="Branch", detail=job.branch),
        StepItem(
            kind="fact",
            title="Pull request",
            detail=job.data.pr_url or "none",
            status=ItemStatus.DONE if job.data.pr_url else ItemStatus.SKIPPED,
        ),
        StepItem(
            kind="fact",
            title="Model calls",
            detail=f"{job.data.invocations} calls, {job.data.tokens_used} tokens",
        ),
    ]
    return [
        StepGroup(
            key="result",
            label="What this development produced",
            items=items,
        )
    ]


def _design_groups(job: Job) -> list[StepGroup]:
    """The screens the Designer wrote, each one unfolding into its states and controls."""
    design = job.data.design or {}
    screens = [
        StepItem(
            kind="screen",
            title=str(s.get("name", "")),
            detail=str(s.get("purpose", "")),
            badges=[Badge(label="", value=str(s.get("platform") or "both"), tone="work")],
            children=[
                StepItem(kind="fact", title="Layout", detail=str(s.get("layout", ""))),
                *(
                    [
                        StepItem(
                            kind="group",
                            title="components",
                            children=[
                                StepItem(kind="part", title=str(c))
                                for c in s.get("components") or []
                            ],
                        )
                    ]
                    if s.get("components")
                    else []
                ),
                *(
                    [
                        StepItem(
                            kind="group",
                            title="states",
                            children=[
                                StepItem(kind="part", title=str(v)) for v in s.get("states") or []
                            ],
                        )
                    ]
                    if s.get("states")
                    else []
                ),
                *(
                    [
                        StepItem(
                            kind="group",
                            title="interactions",
                            children=[
                                StepItem(kind="part", title=str(v))
                                for v in s.get("interactions") or []
                            ],
                        )
                    ]
                    if s.get("interactions")
                    else []
                ),
                *(
                    [StepItem(kind="fact", title="Notes", detail=str(s.get("notes")))]
                    if s.get("notes")
                    else []
                ),
            ],
        )
        for s in design.get("screens") or []
    ]
    return [
        StepGroup(
            key="screens",
            label="Screens",
            note="What the Web and Mobile specialists build from.",
            empty="The Designer has not written the screens yet.",
            items=screens,
        ),
        StepGroup(
            key="principles",
            label="Principles",
            note="What holds across every screen.",
            empty="No principle was recorded beyond the screens themselves.",
            items=[
                StepItem(kind="decision", title=str(p))
                for p in design.get("principles") or []
                if str(p).strip()
            ],
        ),
    ]


def groups_for(job: Job, card: StepCard) -> list[StepGroup]:
    if card.gate:
        return _gate_groups(job, card)
    if card.key == "backlog":
        return _backlog_groups(job)
    if card.key == "design":
        return _design_groups(job)
    if card.key == "architecture":
        return _architecture_groups(job)
    if card.key.startswith("phase:") and card.phase:
        return _phase_groups(job, card.phase)
    if card.key == "qa:1":
        return _qa_cases_groups(job)
    if card.key == "qa:2":
        return _qa_tests_groups(job, card)
    if card.key == "deploy":
        return _deploy_groups(job)
    if card.key == "devops":
        return _devops_groups(job, card)
    if card.key == "done":
        return _done_groups(job)
    # the generic step (an inserted decision gate is handled above): its own record
    return [_history_group(job, list(card.outputs), key="events", label="What happened")]


def step_detail(job: Job, key: str) -> StepDetail | None:
    """Everything recorded for one step of one development, or ``None`` when the job has
    no such step (the key comes from the lane, so this means it moved on)."""
    card = next((c for c in lane_for(job).steps if c.key == key), None)
    if card is None:
        return None
    approved_at, approved_by = _approval(job, card)
    return StepDetail(
        job_id=job.id,
        key=card.key,
        label=card.label,
        role=card.role,
        gate=card.gate,
        status=card.status,
        started_at=card.started_at,
        finished_at=card.finished_at,
        elapsed_s=card.elapsed_s,
        approved_at=approved_at,
        approved_by=approved_by,
        summary=_summary_of(job, card),
        groups=[g for g in groups_for(job, card) if g.items or g.empty],
        outputs=card.outputs,
    )


__all__ = [
    "Badge",
    "ItemStatus",
    "StepDetail",
    "StepGroup",
    "StepItem",
    "groups_for",
    "step_detail",
]
