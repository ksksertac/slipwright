"""Job: one unit of work flowing through the Slipwright pipeline.

The state vocabulary is fixed here; which transitions are legal is the
orchestrator's concern. ``history`` is append-only and every entry is timestamped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.profile import Profile


class JobState(StrEnum):
    CREATED = "created"
    ANALYZING = "analyzing"
    AWAITING_PROFILE_APPROVAL = "awaiting_profile_approval"
    PLANNING = "planning"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    DEVELOPING = "developing"
    BUILD_GATE = "build_gate"
    QA = "qa"
    AWAITING_TEST_APPROVAL = "awaiting_test_approval"
    DEVOPS = "devops"
    DONE = "done"
    FAILED = "failed"


APPROVAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.AWAITING_PROFILE_APPROVAL,
        JobState.AWAITING_PLAN_APPROVAL,
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


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    request: str = Field(min_length=1, description="What the job should accomplish.")
    repo_path: Path
    worktree_path: Path | None = None
    port: int | None = Field(default=None, ge=1024, le=65535)
    state: JobState = JobState.CREATED
    profile: Profile | None = None
    created_at: datetime = Field(default_factory=utcnow)
    history: list[Transition] = Field(default_factory=list)

    @property
    def branch(self) -> str:
        return f"slipwright/{self.id}"

    @property
    def is_awaiting_approval(self) -> bool:
        return self.state in APPROVAL_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
