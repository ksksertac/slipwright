"""Job: one unit of work flowing through the Slipwright pipeline.

The state vocabulary is fixed here; which transitions are legal is the
orchestrator's concern. ``history`` is append-only and every entry is timestamped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.profile import Profile


class JobState(StrEnum):
    CREATED = "created"
    BACKLOG = "backlog"  # the Product Owner writes epics, stories and tasks
    AWAITING_BACKLOG_APPROVAL = "awaiting_backlog_approval"
    ARCHITECTURE = "architecture"  # the Architect proposes profile, decisions and phases
    AWAITING_ARCHITECTURE_APPROVAL = "awaiting_architecture_approval"
    DEVELOPING = "developing"
    BUILD_GATE = "build_gate"
    REVIEW = "review"  # QA checks the phase diff against the standards (T9.5)
    AWAITING_REVIEW_APPROVAL = "awaiting_review_approval"
    QA = "qa"
    AWAITING_TEST_APPROVAL = "awaiting_test_approval"
    DEVOPS = "devops"
    DONE = "done"
    FAILED = "failed"


APPROVAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.AWAITING_BACKLOG_APPROVAL,
        JobState.AWAITING_ARCHITECTURE_APPROVAL,
        JobState.AWAITING_REVIEW_APPROVAL,
        JobState.AWAITING_TEST_APPROVAL,
    }
)
TERMINAL_STATES: frozenset[JobState] = frozenset({JobState.DONE, JobState.FAILED})


def utcnow() -> datetime:
    return datetime.now(UTC)


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
    """Working state that phases read and write. Persisted with the job, never in history."""

    model_config = ConfigDict(extra="forbid")

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
    phase_index: int = Field(default=0, ge=0, description="Next plan phase to execute.")
    build_attempts: int = Field(default=0, ge=0)
    last_build_output: str | None = None
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
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    qa_stage: int = Field(default=1, ge=1, le=2)
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
    jira_last_error: str | None = Field(
        default=None, description="Why the last Jira sync failed; cleared when it succeeds."
    )
    jira_done: list[str] = Field(
        default_factory=list, description="Idempotency keys of agent Jira actions executed."
    )
    jira_queue: list[dict[str, Any]] = Field(
        default_factory=list, description="Agent Jira actions waiting for Jira to come back."
    )


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    project_id: str | None = Field(
        default=None,
        description="Owning project. Every job the engine creates has one; only workspace-"
        "level code (and its tests) builds jobs without.",
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
        return f"slipwright/{self.id}"

    @property
    def is_awaiting_approval(self) -> bool:
        return self.state in APPROVAL_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def pending_messages(self) -> list[InboxMessage]:
        return [m for m in self.data.inbox if m.pending]
