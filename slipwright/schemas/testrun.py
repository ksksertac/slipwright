"""Test run: one execution of the project's test command, on demand or by the build gate.

Output goes to a per-run file (``output_path``) so the database stays small; the API
serves it back through ``GET /test-runs/{id}/output``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.job import new_job_id, utcnow


class TestRunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"  # could not run at all (no checkout, no profile, crashed)


class TestRunSource(StrEnum):
    MANUAL = "manual"  # started by a human through the API
    GATE = "gate"  # a build gate run recorded by the engine


class TestRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    project_id: str
    job_id: str | None = None
    source: TestRunSource = TestRunSource.MANUAL
    command: str
    cwd: Path
    status: TestRunStatus = TestRunStatus.RUNNING
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    exit_code: int | None = None
    output_path: Path | None = None
    note: str | None = Field(default=None, description="What the run was for, or why it errored.")
    phase: int | None = Field(
        default=None, description="The plan phase a build-gate run was for (1-based)."
    )

    @property
    def duration_s(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def terminal(self) -> bool:
        return self.status is not TestRunStatus.RUNNING


__all__ = ["TestRun", "TestRunSource", "TestRunStatus"]
