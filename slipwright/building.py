"""The build room: one development's phases as they are written and built, and who is
writing them.

A development's phases are written by models -- the server's own, a machine lent to the
account, or several at once (T16.3, T17) -- and then applied, built, reviewed, committed
and pushed in their turn, one after another, on the one branch. The pipeline lane shows
each phase as a card; this is the same thing drawn the way it actually happens: machines
on one side, Slipwright in the middle taking each answer in its turn, the branch on the
other side filling up with commits.

Read-only and cheap: it is polled every two seconds while a phase runs, so it reads the
job without its history details and the open machine calls in one query each.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.pipeline import StepStatus, lane_for
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import PLATFORMS
from slipwright.schemas.worker import MachineAbout, Worker
from slipwright.store.workers import WRITES

#: The states in which the room is open: a phase is being written, built, reviewed, or
#: what people did by hand is being read against the plan. Every other state is either a
#: person's turn -- a gate, a pause -- or past the phases.
LIVE: frozenset[JobState] = frozenset(
    {JobState.DEVELOPING, JobState.BUILD_GATE, JobState.REVIEW, JobState.RECONCILE}
)

#: What the phase in its turn is doing, by the job's state.
_STEP = {
    JobState.DEVELOPING: "writing",
    JobState.BUILD_GATE: "building",
    JobState.REVIEW: "reviewing",
    JobState.RECONCILE: "reconciling",
}


class RoomPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    title: str = Field(description="The task it does, else the phase's goal.")
    role: str | None = None
    domain: str | None = None
    status: StepStatus
    commit: str | None = None
    commit_url: str | None = None
    by_hand: bool = False
    parked: bool = False
    # its answer is being written now, by `writer` -- ahead of its turn or in it
    writing: bool = False
    writer: str | None = Field(
        default=None, description="The machine writing it; none when it is this server."
    )
    doing: str | None = Field(default=None, description="What that machine last said.")


class RoomMachine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    online: bool
    lent_by_name: str | None = None
    writes: list[str] = Field(default_factory=list, description="The domains it writes.")
    builds: list[str] = Field(default_factory=list, description="The platforms it builds.")
    about: MachineAbout | None = None
    # a phase of *this* development it is writing; a machine busy with another of the
    # account's developments is shown busy, not idle, but without saying what
    phase: int | None = None
    doing: str | None = None
    elsewhere: bool = False


class RoomServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[str] = Field(
        default_factory=list, description="What the server writes this plan's phases with."
    )
    writing: list[int] = Field(default_factory=list, description="Phases it is writing now.")


class BuildRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: JobState
    live: bool = Field(description="A phase is being written or built: the room is open.")
    branch: str
    pr_url: str | None = None
    slots: int = Field(description="Phases written at once, the one in its turn included.")
    in_turn: int | None = Field(default=None, description="The phase being taken in its turn.")
    step: str | None = Field(
        default=None, description="writing, building, reviewing or reconciling."
    )
    phases: list[RoomPhase]
    machines: list[RoomMachine]
    server: RoomServer


def _phases(job: Job, by_phase: dict[int, dict[str, Any]], written: set[int]) -> list[RoomPhase]:
    """The plan's phases as the lane draws them, each with who is writing it now."""
    out: list[RoomPhase] = []
    for card in lane_for(job).steps:
        if not card.key.startswith("phase:") or card.phase is None:
            continue
        call = by_phase.get(card.phase)
        writing = card.phase in written or call is not None
        out.append(
            RoomPhase(
                number=card.phase,
                title=card.task_title or card.label.split(": ", 1)[-1],
                role=card.role.value if card.role else None,
                domain=card.domain,
                status=card.status,
                commit=card.commit,
                commit_url=card.commit_url,
                by_hand=card.by_hand,
                parked=card.parked,
                writing=writing and card.status is not StepStatus.DONE,
                writer=call.get("worker_name") if call else None,
                doing=call.get("progress") if call else None,
            )
        )
    return out


def _machine(w: Worker, mine: list[dict[str, Any]], busy: set[str]) -> RoomMachine:
    """A machine's card: a phase of this development it writes, or only that it is busy
    with another of the account's."""
    held = next((c for c in mine if str(c["worker_id"]) == w.id), None)
    return RoomMachine(
        id=w.id,
        name=w.name,
        online=w.online,
        lent_by_name=w.lent_by_name,
        writes=[c.removeprefix(WRITES) for c in w.capabilities if c.startswith(WRITES)],
        builds=[c for c in w.capabilities if c in PLATFORMS],
        about=w.about,
        phase=held.get("phase") if held else None,
        doing=held.get("progress") if held else None,
        elsewhere=held is None and w.id in busy,
    )


def build_room(
    job: Job,
    *,
    machines: list[Worker],
    calls: list[dict[str, Any]],
    slots: int,
    models: list[str],
) -> BuildRoom:
    """``calls`` are the account's open machine calls (``open_worker_calls``); only this
    job's say which phase a machine writes, the rest only that it is busy."""
    mine = [c for c in calls if c["job_id"] == job.id]
    by_phase = {int(c["phase"]): c for c in mine if c.get("phase") is not None}
    busy = {str(c["worker_id"]) for c in calls if c.get("worker_id")}
    # what the server writes: every phase written ahead that no machine took, and the one
    # in its turn while it is being written -- unless a machine took that one too
    in_turn = job.data.phase_index + 1 if job.state in LIVE else None
    if job.state is JobState.REVIEW:
        in_turn = job.data.phase_index  # built and committed to the index: being reviewed
    written = {int(n) for n in job.data.ahead}
    if job.state is JobState.DEVELOPING and in_turn is not None:
        written.add(in_turn)

    phases = _phases(job, by_phase, written)
    return BuildRoom(
        job_id=job.id,
        state=job.state,
        live=job.state in LIVE,
        branch=job.branch,
        pr_url=job.data.pr_url or job.data.draft_pr_url,
        slots=max(1, slots),
        in_turn=in_turn,
        step=_STEP.get(job.state),
        phases=phases,
        machines=[_machine(w, mine, busy) for w in machines],
        server=RoomServer(
            models=models,
            writing=sorted(p.number for p in phases if p.writing and p.number not in by_phase),
        ),
    )


__all__ = ["LIVE", "BuildRoom", "RoomMachine", "RoomPhase", "RoomServer", "build_room"]
