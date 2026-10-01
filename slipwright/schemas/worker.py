"""A machine an account lends its developments, and a build it is asked for (T14.3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Worker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_id: str | None = Field(description="The account it builds for; none on a local install.")
    name: str
    capabilities: list[str] = Field(
        default_factory=list, description="What it said at its last poll it can build."
    )
    paired_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    online: bool = Field(default=False, description="Seen recently enough to be given a build.")


class WorkerTask(BaseModel):
    """A build as the worker is given it: which commands, for how long. The worktree
    itself is fetched separately, being the one part that can be large."""

    model_config = ConfigDict(extra="forbid")

    id: str
    job_id: str
    platform: str
    commands: list[tuple[str, str]] = Field(description="(label, command), run in order.")
    timeout_s: float


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int
    output: str = Field(max_length=2_000_000)
    seconds: float = Field(ge=0)


__all__ = ["TaskResult", "Worker", "WorkerTask"]
