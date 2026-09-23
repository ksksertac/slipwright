"""The pipeline view (T9.9): every development as a lane of step cards.

Each card is derived from the job's persisted state and history alone — nothing extra is
stored — so the view is exact after a restart and identical on every client. A card
knows which history entries hold its output (a backlog, a plan, a diff, a gate log, a
PR), so the UI can open them in place.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from slipwright.activity import pending_approval
from slipwright.roles.specialists import LABEL, specialist_for
from slipwright.schemas.job import Job, JobState, Transition, utcnow
from slipwright.schemas.profile import RoleName


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    WAITING = "waiting"  # for the human


class StepCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str  # stable within a job: "backlog", "phase:2", "test_gate:1", ...
    label: str
    role: RoleName | None = None
    domain: str | None = None
    gate: bool = False
    editable: bool = False  # the gate's material can be changed before approval
    pending: str | None = None  # what the human is asked to approve, when waiting
    status: StepStatus
    phase: int | None = None
    task_title: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_s: float | None = None
    outputs: list[int] = Field(default_factory=list, description="History indexes.")
    recommendation: str | None = None  # the supervisor's decision, on a waiting gate
    confidence: float | None = None
    risk: str | None = None
    auto_approved: bool = False  # this gate was approved by the supervisor


class Lane(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    request: str
    summary: str | None = None  # the architect's one-paragraph summary, once there is a plan
    state: JobState
    created_at: datetime
    pending_approval: str | None
    steps: list[StepCard]


class Pipeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None
    lanes: list[Lane]
    waiting: int  # lanes with a card waiting for the human


_PHASE_NOTE = re.compile(r"^(\w+) phase (\d+)/(\d+)")
_REVIEW_NOTE = re.compile(r"^review phase (\d+)/(\d+)")
_GATE_PASSED = re.compile(r"^build gate passed for phase (\d+)/")
_GATE_FAILED = re.compile(r"^build gate failed (?:on phase|\d+ times on phase) (\d+)")

Span = tuple[int, int]  # history index bounds [lo, hi)


def _elapsed(start: datetime | None, end: datetime | None, now: datetime) -> float | None:
    if start is None:
        return None
    return round(((end or now) - start).total_seconds(), 1)


def _task_titles(job: Job) -> dict[str, str]:
    plan = job.data.plan or {}
    tree = plan.get("breakdown") or job.data.backlog or {}
    titles: dict[str, str] = {}
    for epic in tree.get("epics", []):
        for story in epic.get("stories", []):
            for task in story.get("tasks", []):
                titles[str(task.get("id"))] = str(task.get("title", ""))
    return titles


class _Reader:
    """Answers "when did the job enter / leave this state" from the history."""

    def __init__(self, job: Job) -> None:
        self.job = job
        self.history = job.history
        self.now = utcnow()
        self.failed_from: JobState | None = (
            self.history[-1].from_state if job.state is JobState.FAILED and self.history else None
        )
        self.whole: Span = (0, len(self.history))

    def visits(self, state: JobState, span: Span) -> list[int]:
        lo, hi = span
        return [
            i
            for i in range(lo, hi)
            if self.history[i].to_state is state and self.history[i].from_state is not state
        ]

    def _first(self, span: Span, pred: Callable[[int, Transition], bool]) -> int | None:
        lo, hi = span
        for i in range(lo, hi):
            if pred(i, self.history[i]):
                return i
        return None

    def qa_spans(self) -> tuple[Span, Span]:
        """QA visits the test gate twice; the first approval of it splits the history
        into the test-case stage and the written-tests stage."""
        split = self._first(
            self.whole,
            lambda _i, t: (
                t.from_state is JobState.AWAITING_TEST_APPROVAL
                and (t.note or "").startswith("approved")
            ),
        )
        if split is None:
            return self.whole, (len(self.history), len(self.history))
        return (0, split), (split, len(self.history))

    def stage(
        self,
        *,
        key: str,
        label: str,
        state: JobState,
        role: RoleName | None,
        output_into: JobState | tuple[JobState, ...],
        span: Span | None = None,
        current: bool = True,
    ) -> StepCard:
        """A working step: its latest visit to ``state`` inside ``span``; the output is
        the transition that then left it for ``output_into``. ``current`` says whether
        the job's present state belongs to this card (QA is visited twice).

        ``output_into`` takes several states because a step can leave for more than one:
        the backlog goes to its own gate, or -- under the combined plan gate -- straight
        into the architecture. Naming only one made the card sit at ``pending`` after the
        Product Owner had plainly run."""
        exits = output_into if isinstance(output_into, tuple) else (output_into,)
        span = span or self.whole
        starts = self.visits(state, span)
        start_i = starts[-1] if starts else None
        out_i = (
            self._first(
                (start_i + 1, span[1]),
                lambda _i, t: t.from_state is state and t.to_state in exits,
            )
            if start_i is not None
            else None
        )
        start = self.history[start_i].at if start_i is not None else None
        end: datetime | None = None
        if out_i is not None:
            status, end = StepStatus.DONE, self.history[out_i].at
        elif start_i is not None and self.job.state is state and current:
            status = StepStatus.RUNNING
        elif start_i is not None and self.failed_from is state and current:
            status, end = StepStatus.FAILED, self.history[-1].at
        else:
            status, start = StepStatus.PENDING, None
        outputs = [out_i] if out_i is not None else []
        if status is StepStatus.FAILED:
            outputs.append(len(self.history) - 1)
        return StepCard(
            key=key,
            label=label,
            role=role,
            status=status,
            started_at=start,
            finished_at=end,
            elapsed_s=_elapsed(start, end, self.now),
            outputs=outputs,
        )

    def gate(
        self,
        *,
        key: str,
        label: str,
        state: JobState,
        pending: str,
        editable: bool,
        span: Span | None = None,
        current: bool = True,
    ) -> StepCard:
        span = span or self.whole
        starts = self.visits(state, span)
        start_i = starts[-1] if starts else None
        # the approval that closes a span sits on its boundary (it opens the next one)
        approved_i = (
            self._first(
                (start_i + 1, min(span[1] + 1, len(self.history))),
                lambda _i, t: t.from_state is state and (t.note or "").startswith("approved"),
            )
            if start_i is not None
            else None
        )
        start = self.history[start_i].at if start_i is not None else None
        end: datetime | None = None
        if approved_i is not None:
            status, end = StepStatus.DONE, self.history[approved_i].at
        elif start_i is not None and self.job.state is state and current:
            status = StepStatus.WAITING
        else:
            status, start = StepStatus.PENDING, None
        return StepCard(
            key=key,
            label=label,
            gate=True,
            editable=editable,
            pending=pending if status is StepStatus.WAITING else None,
            status=status,
            started_at=start,
            finished_at=end,
            elapsed_s=_elapsed(start, end, self.now),
            outputs=[start_i] if start_i is not None and status is not StepStatus.PENDING else [],
        )


def _phase_cards(job: Job, r: _Reader) -> list[StepCard]:
    plan = job.data.plan or {}
    phases: list[dict[str, object]] = list(plan.get("phases", []))
    if not phases:
        return [StepCard(key="develop", label="Develop", status=StepStatus.PENDING)]
    titles = _task_titles(job)
    past_dev = job.state in (
        JobState.QA,
        JobState.AWAITING_TEST_APPROVAL,
        JobState.DEVOPS,
        JobState.DONE,
    )
    cards: list[StepCard] = []
    for index, phase in enumerate(phases):
        number = index + 1
        role = specialist_for(str(phase.get("domain") or "general"))
        outputs = [
            i
            for i, t in enumerate(r.history)
            if (m := _PHASE_NOTE.match(t.note or "")) and int(m.group(2)) == number
        ]
        gate_logs = [
            i
            for i, t in enumerate(r.history)
            if (m := (_GATE_PASSED.match(t.note or "") or _GATE_FAILED.match(t.note or "")))
            and int(m.group(1)) == number
        ]
        passed = [
            t
            for t in r.history
            if (m := _GATE_PASSED.match(t.note or "")) and int(m.group(1)) == number
        ]
        start: datetime | None = None
        end: datetime | None = None
        if outputs:
            # the phase started when the job last entered developing before its first output
            for i in range(outputs[0], -1, -1):
                if r.history[i].to_state is JobState.DEVELOPING:
                    start = r.history[i].at
                    break
        in_dev = job.state in (JobState.DEVELOPING, JobState.BUILD_GATE)
        in_review = job.state in (JobState.REVIEW, JobState.AWAITING_REVIEW_APPROVAL)
        if in_review and job.data.phase_index - 1 == index:
            status = StepStatus.RUNNING  # built, the standards review is not settled
            if start is None:
                visits = r.visits(JobState.DEVELOPING, r.whole)
                start = r.history[visits[-1]].at if visits else None
        elif passed or past_dev or job.data.phase_index > index:
            status = StepStatus.DONE
            end = passed[-1].at if passed else None
        elif in_dev and job.data.phase_index == index:
            status = StepStatus.RUNNING
            if start is None:
                visits = r.visits(JobState.DEVELOPING, r.whole)
                start = r.history[visits[-1]].at if visits else None
        elif (
            job.state is JobState.FAILED
            and job.data.phase_index == index
            and r.failed_from in (JobState.DEVELOPING, JobState.BUILD_GATE)
        ):
            status = StepStatus.FAILED
            end = r.history[-1].at
            if start is None:
                visits = r.visits(JobState.DEVELOPING, r.whole)
                start = r.history[visits[-1]].at if visits else None
            gate_logs.append(len(r.history) - 1)
        else:
            status, start = StepStatus.PENDING, None
        cards.append(
            StepCard(
                key=f"phase:{number}",
                label=f"{LABEL[role]}: {phase.get('goal', '')}",
                role=role,
                domain=str(phase.get("domain") or "general"),
                status=status,
                phase=number,
                task_title=titles.get(str(phase.get("task_id"))),
                started_at=start,
                finished_at=end,
                elapsed_s=_elapsed(start, end, r.now),
                outputs=sorted(set(outputs + gate_logs)),
            )
        )
        gate = _review_gate(job, r, number)
        if gate is not None:
            cards.append(gate)
    return cards


def _review_gate(job: Job, r: _Reader, number: int) -> StepCard | None:
    """A "Review approval" card after a phase whose blocking violations reached the
    human: waiting while the job sits at the gate, done once it was decided."""
    visits = [
        i
        for i, t in enumerate(r.history)
        if t.to_state is JobState.AWAITING_REVIEW_APPROVAL
        and (m := _REVIEW_NOTE.match(t.note or ""))
        and int(m.group(1)) == number
    ]
    if not visits:
        return None
    last = visits[-1]
    decided = next(
        (
            i
            for i in range(last + 1, len(r.history))
            if r.history[i].from_state is JobState.AWAITING_REVIEW_APPROVAL
        ),
        None,
    )
    waiting = job.state is JobState.AWAITING_REVIEW_APPROVAL and decided is None
    start = r.history[last].at
    end = r.history[decided].at if decided is not None else None
    return StepCard(
        key=f"review_gate:{number}",
        label=f"Review approval: phase {number}",
        gate=True,
        pending="review" if waiting else None,
        status=StepStatus.WAITING if waiting else StepStatus.DONE,
        phase=number,
        started_at=start,
        finished_at=end,
        elapsed_s=_elapsed(start, end, r.now),
        outputs=[last] + ([decided] if decided is not None else []),
    )


def _insert_decision_gate(job: Job, r: _Reader, steps: list[StepCard]) -> None:
    """While the job waits at the decision gate (a loop, or the supervisor asked), show
    it right after the step it interrupted."""
    if job.state is not JobState.AWAITING_DECISION:
        return
    visits = r.visits(JobState.AWAITING_DECISION, r.whole)
    if not visits:
        return
    resume = job.data.resume_state or ""
    phase = f"phase:{min(job.data.phase_index + 1, max(len(job.history), 1))}"
    anchor = {
        "backlog": "backlog",
        "architecture": "architecture",
        "developing": phase,
        "build_gate": phase,
        "review": phase,
        "qa": "qa:1" if job.data.qa_stage == 1 else "qa:2",
        "devops": "devops",
    }.get(resume, "backlog")
    keys = [c.key for c in steps]
    at = keys.index(anchor) + 1 if anchor in keys else len(steps) - 1
    start = r.history[visits[-1]].at
    steps.insert(
        at,
        StepCard(
            key="decision_gate",
            label="Your decision",
            gate=True,
            pending="decision",
            status=StepStatus.WAITING,
            started_at=start,
            elapsed_s=_elapsed(start, None, r.now),
            outputs=[visits[-1]],
        ),
    )


def _annotate_supervision(job: Job, steps: list[StepCard]) -> None:
    """Put the supervisor's view on the gate it concerns: a recommendation chip while the
    gate waits, an "approved by supervisor" mark once it acted."""
    record = job.data.supervision or {}
    for card in steps:
        if not card.gate:
            continue
        if card.status is StepStatus.WAITING and record and record.get("acted") == "none":
            card.recommendation = record.get("decision")
            card.confidence = record.get("confidence")
            card.risk = record.get("risk")
        elif card.status is StepStatus.DONE and card.outputs:
            visit = card.outputs[0]
            state = job.history[visit].to_state
            for t in job.history[visit + 1 :]:
                if t.from_state is state and (t.note or "").startswith("approved"):
                    card.auto_approved = " by supervisor" in (t.note or "")
                    break


def lane_for(job: Job) -> Lane:
    r = _Reader(job)
    stage1, stage2 = r.qa_spans()
    in_stage1 = job.data.qa_stage == 1
    # the combined plan gate never stops at the backlog on its own: showing a gate card
    # that will never be reached reads as a step still to come, which it is not
    combined = job.data.plan_gate == "combined"
    steps: list[StepCard] = [
        r.stage(
            key="backlog",
            label="Backlog",
            state=JobState.BACKLOG,
            role=RoleName.PO,
            output_into=(JobState.AWAITING_BACKLOG_APPROVAL, JobState.ARCHITECTURE),
        ),
        *(
            []
            if combined
            else [
                r.gate(
                    key="backlog_gate",
                    label="Backlog approval",
                    state=JobState.AWAITING_BACKLOG_APPROVAL,
                    pending="backlog",
                    editable=True,
                )
            ]
        ),
        r.stage(
            key="architecture",
            label="Architecture",
            state=JobState.ARCHITECTURE,
            role=RoleName.ARCHITECT,
            output_into=JobState.AWAITING_ARCHITECTURE_APPROVAL,
        ),
        r.gate(
            key="architecture_gate",
            label="Architecture approval",
            state=JobState.AWAITING_ARCHITECTURE_APPROVAL,
            pending="architecture",
            editable=True,
        ),
        *_phase_cards(job, r),
        r.stage(
            key="qa:1",
            label="QA: test cases",
            state=JobState.QA,
            role=RoleName.QA,
            output_into=JobState.AWAITING_TEST_APPROVAL,
            span=stage1,
            current=in_stage1,
        ),
        r.gate(
            key="test_gate:1",
            label="Test cases approval",
            state=JobState.AWAITING_TEST_APPROVAL,
            pending="test cases",
            editable=True,
            span=stage1,
            current=in_stage1,
        ),
        r.stage(
            key="qa:2",
            label="QA: write tests",
            state=JobState.QA,
            role=RoleName.QA,
            output_into=JobState.AWAITING_TEST_APPROVAL,
            span=stage2,
            current=not in_stage1,
        ),
        r.gate(
            key="test_gate:2",
            label="Written tests approval",
            state=JobState.AWAITING_TEST_APPROVAL,
            pending="written tests",
            editable=False,
            span=stage2,
            current=not in_stage1,
        ),
        r.stage(
            key="devops",
            label="DevOps",
            state=JobState.DEVOPS,
            role=RoleName.DEVOPS,
            output_into=JobState.DONE,
        ),
        StepCard(
            key="done",
            label="Done",
            status=StepStatus.DONE if job.state is JobState.DONE else StepStatus.PENDING,
            finished_at=job.history[-1].at if job.state is JobState.DONE else None,
        ),
    ]
    _insert_decision_gate(job, r, steps)
    _annotate_supervision(job, steps)
    return Lane(
        job_id=job.id,
        request=job.request,
        summary=str((job.data.plan or {}).get("summary") or "").strip() or None,
        state=job.state,
        created_at=job.created_at,
        pending_approval=pending_approval(job),
        steps=steps,
    )


def pipeline(jobs: list[Job], *, project_id: str | None = None) -> Pipeline:
    lanes = [lane_for(j) for j in jobs]
    return Pipeline(
        project_id=project_id,
        lanes=lanes,
        waiting=sum(1 for lane in lanes if lane.pending_approval),
    )


__all__ = ["Lane", "Pipeline", "StepCard", "StepStatus", "lane_for", "pipeline"]
