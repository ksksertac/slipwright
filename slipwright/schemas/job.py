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
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

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
    DONE = "done"
    FAILED = "failed"


APPROVAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.AWAITING_BACKLOG_APPROVAL,
        JobState.AWAITING_ARCHITECTURE_APPROVAL,
        JobState.AWAITING_DESIGN_APPROVAL,
        JobState.AWAITING_REVIEW_APPROVAL,
        JobState.AWAITING_TEST_APPROVAL,
        JobState.AWAITING_DEPLOY_APPROVAL,
        JobState.AWAITING_DECISION,
    }
)
TERMINAL_STATES: frozenset[JobState] = frozenset({JobState.DONE, JobState.FAILED})


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
        "ı": "i", "İ": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
        "ş": "s", "Ş": "s", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
        "â": "a", "î": "i", "û": "u", "é": "e", "è": "e", "ñ": "n",
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


class InboxMessage(BaseModel):
    """A steering message from the human, delivered to the next role invocation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id)
    text: str = Field(min_length=1)
    at: datetime = Field(default_factory=utcnow)
    consumed_at: datetime | None = None
    consumed_by: str | None = None

    @property
    def pending(self) -> bool:
        return self.consumed_at is None


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
    # -- hardening (T9.7) --
    resume_state: str | None = Field(
        default=None, description="Where the job continues after the decision gate."
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
        description="One entry per model call: role, phase, attempts, prompt_chars, tokens, at.",
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
    pr_url: str | None = None
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
    repo_path: Path
    worktree_path: Path | None = None
    port: int | None = Field(default=None, ge=1024, le=65535)
    state: JobState = JobState.CREATED
    profile: Profile | None = None
    created_at: datetime = Field(default_factory=utcnow)
    history: list[Transition] = Field(default_factory=list)
    data: JobData = Field(default_factory=JobData)

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
    def pending_messages(self) -> list[InboxMessage]:
        return [m for m in self.data.inbox if m.pending]
