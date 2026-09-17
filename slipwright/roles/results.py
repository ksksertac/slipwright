"""Per-role structured result schemas.

Every role invocation must produce output that validates against the schema registered
for that role here. The invoke layer uses ``RESULT_SCHEMAS`` both to constrain the model's
output format and to validate what comes back. Later phases refine these models; the
registry and the "one schema per role" rule are the contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.profile import Profile, RoleName


class RoleOutput(BaseModel):
    """Base for all role outputs. ``extra="forbid"`` keeps the JSON Schema closed."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, description="One-paragraph account of what was done.")


class AnalystResult(RoleOutput):
    profile: Profile = Field(description="Project profile inferred from the worktree.")


class PlanPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list, description="Files expected to change.")


class PlannerResult(RoleOutput):
    phases: list[PlanPhase] = Field(min_length=1)


class DeveloperResult(RoleOutput):
    files_changed: list[str] = Field(default_factory=list)
    phase_complete: bool = Field(description="Whether the assigned plan phase is finished.")


class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class QAResult(RoleOutput):
    test_cases: list[TestCase] = Field(default_factory=list)
    tests_written: list[str] = Field(
        default_factory=list, description="Test files written in stage two."
    )


class DevOpsResult(RoleOutput):
    pr_url: str | None = None
    ci_passed: bool | None = None


RESULT_SCHEMAS: dict[RoleName, type[RoleOutput]] = {
    RoleName.ANALYST: AnalystResult,
    RoleName.PLANNER: PlannerResult,
    RoleName.DEVELOPER: DeveloperResult,
    RoleName.QA: QAResult,
    RoleName.DEVOPS: DevOpsResult,
}


def result_schema_for(role: RoleName) -> type[RoleOutput]:
    return RESULT_SCHEMAS[role]


__all__ = [
    "RESULT_SCHEMAS",
    "AnalystResult",
    "DevOpsResult",
    "DeveloperResult",
    "PlanPhase",
    "PlannerResult",
    "QAResult",
    "RoleOutput",
    "TestCase",
    "result_schema_for",
]
