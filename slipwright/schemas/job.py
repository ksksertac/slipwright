"""Job: one unit of work flowing through the Slipwright pipeline.

The state vocabulary is fixed here; which transitions are legal is the
orchestrator's concern. ``history`` is append-only and every entry is timestamped.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from slipwright.schemas.profile import Profile

_EPOCH = datetime.fromtimestamp(0, UTC)


class JobState(StrEnum):
    CREATED = "created"
    BACKLOG = "backlog"  # the Product Owner writes epics, stories and tasks
    AWAITING_BACKLOG_APPROVAL = "awaiting_backlog_approval"
    ARCHITECTURE = "architecture"  # the Architect proposes profile, decisions and phases
    AWAITING_ARCHITECTURE_APPROVAL = "awaiting_architecture_approval"
    DESIGN = "design"  # the Designer draws the screens the UI specialists build
    # the screens are signed off one at a time, and only the UI phases wait for them
    AWAITING_DESIGN_APPROVAL = "awaiting_design_approval"
    DEVELOPING = "developing"
    BUILD_GATE = "build_gate"
    REVIEW = "review"  # QA checks the phase diff against the standards (T9.5)
    AWAITING_REVIEW_APPROVAL = "awaiting_review_approval"
    QA = "qa"
    AWAITING_TEST_APPROVAL = "awaiting_test_approval"
    DEVOPS = "devops"
    AWAITING_DEPLOY_APPROVAL = "awaiting_deploy_approval"  # the deployment scripts (T11.6)
    AWAITING_DECISION = "awaiting_decision"  # stuck (loop, or the supervisor asked): T9.7
    # what is left is mobile phases nothing here can build (T14.2): not a gate -- nobody
    # approves it -- it opens by itself when a machine that can build them connects
    AWAITING_BUILDER = "awaiting_builder"
    # somebody paused it to work on the branch by hand: not over, and nothing runs it until
    # the same person says carry on -- with what was pushed meanwhile, or without
    PAUSED = "paused"
    # what people did on the branch while it was paused, read by the Architect against the
    # plan, and the person's yes before the phases they finished are passed over
    RECONCILE = "reconcile"
    AWAITING_RECONCILE_APPROVAL = "awaiting_reconcile_approval"
    DONE = "done"
    # somebody stopped it: not a failure, and not something to retry into
    CANCELLED = "cancelled"
    FAILED = "failed"


APPROVAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.AWAITING_BACKLOG_APPROVAL,
        JobState.AWAITING_ARCHITECTURE_APPROVAL,
        JobState.AWAITING_DESIGN_APPROVAL,
        JobState.AWAITING_REVIEW_APPROVAL,
        JobState.AWAITING_TEST_APPROVAL,
        JobState.AWAITING_DEPLOY_APPROVAL,
        JobState.AWAITING_RECONCILE_APPROVAL,
        JobState.AWAITING_DECISION,
    }
)
TERMINAL_STATES: frozenset[JobState] = frozenset(
    {JobState.DONE, JobState.FAILED, JobState.CANCELLED}
)


_CLOCK = threading.Lock()
_LAST_US = 0


def utcnow() -> datetime:
    """Now -- but never the same instant twice.

    Windows moves the system clock in steps of about 16ms, so a burst of writes all carry
    the same timestamp: 2000 calls here produced three distinct values. Anything ordered
    by one then falls back to its tie-break -- a random id, for jobs -- and the list comes
    back shuffled. Each call is nudged one microsecond past the last one, which costs
    nothing and makes every timestamp this process writes strictly increasing.
    """
    global _LAST_US
    with _CLOCK:
        us = max(int(time.time() * 1_000_000), _LAST_US + 1)
        _LAST_US = us
    return _EPOCH + timedelta(microseconds=us)


#: Turkish (and the rest of Latin-1) folded to ASCII, so a branch name stays typeable on
#: any keyboard and git never has to carry bytes a shell will mangle.
_FOLD = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
        "â": "a",
        "î": "i",
        "û": "u",
        "é": "e",
        "è": "e",
        "ñ": "n",
    }
)


def slugify(text: str, *, limit: int = 40) -> str:
    """``text`` as a branch-safe slug: ascii, lower case, words joined by hyphens.

    Empty when there is nothing usable left, which the caller has to handle -- a branch
    name is never allowed to end up as a bare hyphen or an empty segment.
    """
    out: list[str] = []
    for ch in text.translate(_FOLD).lower():
        if ch.isascii() and (ch.isalnum()):
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out)[:limit].strip("-")
    # git refuses a component ending in ".lock" and treats a leading "-" as a flag
    return slug if not slug.endswith(".lock") else slug[:-5].strip("-")


#: The longest name a development is shown by. Long enough for "Android quiz app with
#: Bluetooth rooms", short enough for a table cell, a chat line and an email subject.
TITLE_MAX = 80


def headline(request: str, limit: int = TITLE_MAX) -> str:
    """A name for a development nobody named: the first sentence of what was asked,
    clipped at a word. Only for a request that came without a title -- a chat message, the
    CLI, a job from before titles existed; the form asks for one."""
    first = request.strip().splitlines()[0] if request.strip() else ""
    for stop in (". ", "? ", "! "):
        if stop in first:
            first = first.split(stop, 1)[0]
    first = first.strip().rstrip(".!?")
    if len(first) <= limit:
        return first
    clipped = first[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return f"{clipped or first[: limit - 1]}…"


def branch_name(project: str, request: str, job_id: str) -> str:
    """``<project>/<what-was-asked>-<short id>``.

    The name a person reads on GitHub, so it says which project it belongs to and what it
    was for. The short id is what keeps two goes at the same request apart, and it is why
    the slug never has to be unique.
    """
    where = slugify(project, limit=24) or "slipwright"
    what = slugify(request, limit=40)
    tail = job_id[:8]
    return f"{where}/{what}-{tail}" if what else f"{where}/{tail}"


#: Where a development can be planned again while it is being built: from an approved
#: plan to its last phase, running or waiting on something on the way. Not before the
#: plan -- there is nothing to plan again -- and not after the phases, when what is left
#: is testing what was built.
REDIRECTABLE: frozenset[JobState] = frozenset(
    {
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        JobState.REVIEW,
        JobState.AWAITING_DECISION,
        JobState.AWAITING_REVIEW_APPROVAL,
        JobState.AWAITING_BUILDER,
        JobState.AWAITING_DESIGN_APPROVAL,
    }
)


def new_job_id() -> str:
    return uuid4().hex[:12]


class Transition(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_state: JobState
    to_state: JobState
    at: datetime
    note: str | None = None
    detail: str | None = Field(
        default=None, description="Long-form record for this step: a diff, a build log, ..."
    )
    detail_size: int | None = Field(
        default=None,
        description="How long `detail` is, in characters. A job read without its details "
        "(the lists, and the page that follows a development) carries this and not "
        "`detail`: GET /jobs/{id}/history/{index} is the entry with it.",
    )

    @property
    def has_detail(self) -> bool:
        return bool(self.detail) or bool(self.detail_size)


class InboxMessage(BaseModel):
    """A steering message from the human, delivered to the next role invocation.

    Kept in the ``job_messages`` table, not in the job's data: the store fills
    ``JobData.inbox`` from there when a job is read and adds to it when one is saved,
    never taking anything away (see ``JobStore.save``)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id)
    text: str = Field(min_length=1)
    at: datetime = Field(default_factory=utcnow)
    consumed_at: datetime | None = None
    consumed_by: str | None = None
    # who it is for: an instruction about phase 8 is the mobile specialist's, and the
    # standards review that runs between two of its calls must not read it and use it up
    role: str | None = None
    phase: int | None = Field(default=None, description="The 1-based phase it is about.")

    @property
    def pending(self) -> bool:
        return self.consumed_at is None

    def for_call(self, role: str, phase: int | None) -> bool:
        """Whether a call by ``role`` on ``phase`` is the one this was written for."""
        if self.role is not None and self.role != role:
            return False
        return self.phase is None or phase is None or self.phase == phase


MessageKind = Literal["steer", "question", "replan"]


class JobMessage(BaseModel):
    """One thing a person said to a development's agents, and what came back.

    ``status`` reads by kind: a steer is ``pending`` until an agent's call reads it, then
    ``read``; a question is ``answering``, then ``answered`` or ``failed``; a re-plan is
    ``pending`` until the run reaches a place it can stop, then ``applied``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id)
    job_id: str
    kind: MessageKind
    text: str = Field(min_length=1)
    by: str | None = None
    at: datetime = Field(default_factory=utcnow)
    step: str | None = None
    phase: int | None = None
    role: str | None = None
    reply_to: str | None = None
    status: str
    answer: str | None = None
    change: str | None = Field(
        default=None,
        description="What the agent understood the person to want changed, when the "
        "question was a request. Nothing is changed until the person says so.",
    )
    error: str | None = None
    answered_at: datetime | None = None
    consumed_at: datetime | None = None
    consumed_by: str | None = None


class JobData(BaseModel):
    """Working state that phases read and write. Persisted with the job, never in history.

    Unknown keys are kept rather than refused: a job written by a newer build must still
    load in an older one — a rollback, or a second process on the same database — and the
    fields that build added must survive the round trip instead of being dropped or
    bringing the server down.
    """

    model_config = ConfigDict(extra="allow")

    base_commit: str | None = Field(default=None, description="Commit the job branched from.")
    feedback: str | None = Field(default=None, description="Rejection feedback for a re-run.")
    reject_rounds: int = Field(default=0, ge=0)
    backlog: dict[str, Any] | None = Field(
        default=None, description="The Product Owner's breakdown (epics/stories/tasks)."
    )
    plan: dict[str, Any] | None = Field(
        default=None,
        description="The Architect's plan: summary, decisions, phases and the breakdown "
        "with phase numbers filled in.",
    )
    language: str = Field(
        default="en", description="The project's language for people-facing text."
    )
    brief: list[dict[str, Any]] = Field(
        default_factory=list,
        description="The project brief as it stood when this job started: what the agents "
        "were told the project is (see slipwright/schemas/brief.py).",
    )
    plan_gate: str = Field(
        default="separate",
        description="combined: the backlog flows straight into the architecture and both "
        "are approved as one work list.",
    )
    design: dict[str, Any] | None = Field(
        default=None,
        description="The Designer's screens and principles; the UI specialists build from "
        "it. None when the development has no screen in it.",
    )
    design_approvals: dict[str, bool] = Field(
        default_factory=dict,
        description="Screen id -> signed off by a person. The web and mobile phases wait "
        "until every screen is in here; the backend phases never do.",
    )
    design_feedback: dict[str, str] = Field(
        default_factory=dict,
        description="Screen id -> what the person asked to be different. The Designer draws "
        "those screens again and leaves the rest as they are.",
    )
    branch_name: str = Field(
        default="",
        description="The branch this job works on. Empty on jobs made before it was "
        "recorded, which fall back to the old slipwright/<id>.",
    )
    phase_index: int = Field(default=0, ge=0, description="Next plan phase to execute.")
    build_attempts: int = Field(default=0, ge=0)
    last_build_output: str | None = None
    qa_gate_fixes: int = Field(
        default=0,
        ge=0,
        description="Times QA judged the failing test itself wrong on this phase and "
        "corrected it. Bounded, so a test and a change cannot chase each other.",
    )
    qa_diagnosis: str | None = Field(
        default=None,
        description="QA's reading of the last failed build gate when the code, not the "
        "test, was the side that was wrong. The specialist fixing it reads this.",
    )
    rerun_only: bool = Field(
        default=False,
        description="A step the human re-ran by hand: a passing build gate stops there "
        "instead of carrying the finished development through the pipeline again.",
    )
    phase_base_commit: str | None = Field(
        default=None, description="HEAD when the current phase started; the review diffs from it."
    )
    review_rounds: int = Field(
        default=0, ge=0, description="Fix rounds the current phase went through after review."
    )
    review_violations: list[dict[str, Any]] = Field(
        default_factory=list, description="Blocking violations the specialist must fix now."
    )
    reviews: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Every standards review: phase, round, mode, violations, verdict.",
    )
    supervision: dict[str, Any] | None = Field(
        default=None,
        description="The supervisor's view of the current or last gate: gate, decision, "
        "confidence, risk, reasons, feedback, acted (none | auto | error), undone.",
    )
    auto_approvals: int = Field(default=0, ge=0, description="Gates the supervisor approved.")
    notified: list[str] = Field(
        default_factory=list,
        description="Gates whose agent's team has already been written to, as "
        "'<state>:<visit>'. Kept on the job so a restart does not write the letter "
        "again and a gate reached twice writes it twice.",
    )
    waiting_platforms: list[str] = Field(
        default_factory=list,
        description="While the job waits for a builder: the mobile platforms (ios, android) "
        "its remaining phases need and nothing here can build (T14.2).",
    )
    builder_resume: str | None = Field(
        default=None,
        description="Where a builder arriving picks the job up: developing, or build_gate "
        "when a Mac went away with the phase already written (T14.3).",
    )
    # -- hardening (T9.7) --
    resume_state: str | None = Field(
        default=None, description="Where the job continues after the decision gate."
    )
    parked: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Phases set aside after spending their budget while others could go on "
        "(by their number now): their uncommitted work as a patch, their counters, and why. "
        "Restored, and asked about, when their turn comes again.",
    )
    ahead: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Phases whose answer is being written ahead of their turn (T16.3), by "
        "number: who writes it and since when. What is shown; the answers themselves are "
        "held by the running server, and one that restarts writes them again in turn.",
    )
    replan_from: int | None = Field(
        default=None,
        description="While the plan is being made again from a phase on: that phase's index "
        "(0-based). The phases before it are built and committed, and stay as they are.",
    )
    # -- one budget for a phase (T15.5) --
    phase_calls: int = Field(
        default=0,
        ge=0,
        description="Model calls made for `phase_calls_for` since it started or since a "
        "person last answered for it: building, fixing, triage and review alike.",
    )
    phase_calls_for: int | None = Field(
        default=None, description="The phase (1-based) `phase_calls` counts."
    )
    decision_kind: str | None = Field(
        default=None,
        description="Why the decision gate stopped, when that changes what it offers: "
        '"phase_budget" waits for a written answer and offers no plain approve.',
    )
    recommendation_route: str | None = Field(
        default=None,
        description='Who QA says should act on the recommendation: "developer" (try again '
        'with it) or "architect" (plan the phase again).',
    )
    recommendation: str | None = Field(
        default=None,
        description="What QA proposes at a phase-budget stop, for the person to accept as "
        "written or rewrite.",
    )
    invocations: int = Field(default=0, ge=0, description="Model calls made so far.")
    tokens_used: int = Field(default=0, ge=0, description="Input + output tokens so far.")
    cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="What the model calls have cost so far, in US dollars. Calls whose "
        "model has no stored price add nothing, and are listed as unpriced.",
    )
    invocation_log: list[dict[str, Any]] = Field(
        default_factory=list,
        description="One entry per model call: role, provider, model, phase, attempts, "
        "prompt_chars, tokens, cost, how long it took, the start of what it wrote, at.",
    )
    inflight: dict[str, Any] | None = Field(
        default=None,
        description="The model call being waited on right now -- role, provider, model, "
        "phase, started_at -- so a page can say who was asked and how long ago before the "
        "answer exists. Cleared when the call is logged; no provider streams, so the answer "
        "itself only ever arrives whole.",
    )
    output_hashes: dict[str, str] = Field(
        default_factory=dict, description="(role:phase) -> hash of the last output (loop check)."
    )
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    qa_stage: int = Field(default=1, ge=1, le=2)
    tests_skipped: bool = Field(
        default=False,
        description="The test cases were read and deliberately not taken up: QA writes "
        "nothing and the development goes straight to DevOps. Writing tests is the most "
        "expensive step there is, and it is not always worth it.",
    )
    devops_stage: int = Field(
        default=1,
        ge=1,
        le=2,
        description="1: DevOps proposes how this is deployed; 2: it writes the scripts "
        "and opens the pull request (T11.6).",
    )
    deploy: dict[str, Any] | None = Field(
        default=None,
        description="The deployment proposal: target, services, scripts, notes. Approved "
        "(and possibly edited) by a person before anything is written.",
    )
    deploy_written: list[str] = Field(
        default_factory=list, description="Deployment files written into the branch."
    )
    deploy_skipped: bool = Field(
        default=False,
        description="The deployment proposal was read and deliberately not taken up: "
        "DevOps writes no deployment files and opens the pull request with the code "
        "alone. The deployment may be done by hand, or not wanted at all.",
    )
    readme_written: bool = Field(
        default=False,
        description="The Architect has written the project's README for this development, "
        "or tried and could not: it is asked once, before the pull request.",
    )
    pr_url: str | None = None
    phase_commits: dict[str, str] = Field(
        default_factory=dict,
        description="Phase number -> the commit that recorded it, for the pipeline's link.",
    )
    draft_pr_url: str | None = Field(
        default=None,
        description="The pull request opened as a draft at the first push (T16.1), so the "
        "work can be followed on the host as it is built. `pr_url` is set when DevOps "
        "finishes it; until then everything that waits for a pull request still waits.",
    )
    ci_attempts: int = Field(default=0, ge=0)
    inbox: list[InboxMessage] = Field(default_factory=list)
    jira_keys: dict[str, str] = Field(
        default_factory=dict, description="Breakdown item id -> Jira issue key, once synced."
    )
    jira_status: dict[str, str] = Field(
        default_factory=dict, description="Breakdown item id -> last status pushed to Jira."
    )
    jira_marks: list[str] = Field(
        default_factory=list, description="One-shot Jira comments already posted."
    )
    jira_sprint_id: int | None = Field(
        default=None, description="The sprint the mirrored stories were put into."
    )
    jira_last_error: str | None = Field(
        default=None, description="Why the last Jira sync failed; cleared when it succeeds."
    )
    jira_done: list[str] = Field(
        default_factory=list, description="Idempotency keys of agent Jira actions executed."
    )
    jira_queue: list[dict[str, Any]] = Field(
        default_factory=list, description="Agent Jira actions waiting for Jira to come back."
    )
    # -- pausing to work by hand --
    pause: dict[str, Any] | None = Field(
        default=None,
        description="While paused, and after: where it stopped (from_state, phase_index), "
        "the commit it stopped on (head), who paused it and when, and -- when the branch was "
        "pushed so people could work on it -- the commit pushed (pushed), whether unfinished "
        "work was committed to get it there (wip), and why a push failed (push_error).",
    )
    # -- deleted --
    removed: dict[str, Any] | None = Field(
        default=None,
        description="Set once the development was deleted: who and when (by, at), and what "
        "was taken off the host -- pull requests closed (prs_closed), the branch "
        "(branch_deleted), the revert pushed onto the base branch when it had been merged "
        "(reverted: {onto, commit, commits}), Jira issues marked Won't Do (jira_closed) or "
        "offering no such move (jira_left) -- and whatever could not be (errors). A "
        "deleted development is kept to be read; nothing moves it again. It lives here "
        "rather than as a state of its own so that a release rolled back can still read it.",
    )
    reconcile: dict[str, Any] | None = Field(
        default=None,
        description="The Architect's reading of what people pushed while the development "
        "was paused: per remaining phase done, partial or untouched, and the phase it carries "
        "on from. Approved at its own gate before anything is passed over.",
    )
    phase_outcomes: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Phase number (1-based, as a string) -> how it was finished, for the "
        "phases somebody finished by hand: {by: 'hand', evidence}. Agent-built phases are "
        "not listed; the history already says how they went.",
    )


class ChangedFile(BaseModel):
    """One file of the branch's diff against the commit it started from."""

    model_config = ConfigDict(extra="forbid")

    path: str
    added: int
    removed: int


class Commit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha: str
    subject: str


class JobResult(BaseModel):
    """What a development produced, for the person who has to use it."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: JobState
    branch: str
    checkout: str  # the repository the branch lives in
    base_branch: str
    merged: bool  # the base branch already contains the branch's tip
    pr_url: str | None = None
    commits: list[Commit] = Field(default_factory=list)
    files: list[ChangedFile] = Field(default_factory=list)
    added: int = 0
    removed: int = 0
    summary: str = ""  # the DevOps write-up, or the last step's summary
    merge_command: str | None = None
    problem: str | None = None  # why the result could not be read


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    project_id: str | None = Field(
        default=None,
        description="Owning project. Every job the engine creates has one; only workspace-"
        "level code (and its tests) builds jobs without.",
    )
    owner_id: str | None = Field(
        default=None,
        description="Copied from the project when the job is created. It decides who may "
        "see the job and, once it runs, whose model keys pay for it.",
    )
    request: str = Field(min_length=1, description="What the job should accomplish.")
    title: str = Field(
        default="",
        description="The short name the development is shown by everywhere -- lists, "
        "chat messages, emails. The request stays the agents' brief; this is only its name. "
        "Empty on the way in means derived from the request (``headline``).",
    )
    repo_path: Path
    worktree_path: Path | None = None
    port: int | None = Field(default=None, ge=1024, le=65535)
    state: JobState = JobState.CREATED
    profile: Profile | None = None
    created_at: datetime = Field(default_factory=utcnow)
    history: list[Transition] = Field(default_factory=list)
    data: JobData = Field(default_factory=JobData)

    @model_validator(mode="after")
    def _named(self) -> Job:
        # every job has a name, however it was made: a job without one would be shown by
        # its whole request again, which is what titles are here to stop
        self.title = self.title.strip() or headline(self.request)
        return self

    @property
    def branch(self) -> str:
        """The branch this job's work lives on, in the project's own checkout.

        Written down at creation rather than computed, because a job already running has
        that branch in git under the name it was given: changing the formula must never
        rename a branch out from under a development. Jobs made before the name was
        recorded keep the one they were created with.
        """
        return self.data.branch_name or f"slipwright/{self.id}"

    @property
    def is_awaiting_approval(self) -> bool:
        return self.state in APPROVAL_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_removed(self) -> bool:
        """Deleted: kept to be read, and nothing moves it again."""
        return self.data.removed is not None

    @property
    def pending_messages(self) -> list[InboxMessage]:
        return [m for m in self.data.inbox if m.pending]
