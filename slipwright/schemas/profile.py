"""Project profile: the contract that makes the engine project-agnostic.

A profile describes the project under test (how to build, test and run it) and, per
role, which model to use, how deeply it should think and what it is allowed to do.
Engine code never names a model; it only reads ``profile.roles[role].model``.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import ErrorDetails

PORT_PLACEHOLDER = "{port}"


class RoleName(StrEnum):
    PO = "po"  # product owner: request -> epics, stories, tasks
    ARCHITECT = "architect"  # backlog + repository -> profile, decisions, phases
    DEVELOPER = "developer"  # generic implementer; specialists below take tagged phases
    BACKEND = "backend"
    WEB_UI = "web_ui"
    MOBILE_UI = "mobile_ui"
    QA = "qa"
    DEVOPS = "devops"
    SUPERVISOR = "supervisor"  # recommends (or, in auto mode, gives) gate approvals


class ThinkingDepth(StrEnum):
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class Permission(StrEnum):
    READ_FILES = "read_files"
    WRITE_FILES = "write_files"
    RUN_COMMANDS = "run_commands"
    NETWORK = "network"
    GIT_PUSH = "git_push"
    JIRA = "jira"  # may return jira_actions the engine executes (T7.5)


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, description="Model identifier passed to the provider.")
    provider: str | None = Field(
        default=None,
        description="Which provider serves this role (anthropic, openai, deepseek); "
        "unset means the configured default.",
    )
    thinking_depth: ThinkingDepth
    permissions: list[Permission] = Field(default_factory=list)
    standards_budget: int | None = Field(
        default=None,
        ge=0,
        description="Token budget for the standards sections retrieved into this role's "
        "prompt; unset means the value under Settings → Standards.",
    )

    @field_validator("permissions")
    @classmethod
    def _unique_permissions(cls, value: list[Permission]) -> list[Permission]:
        if len(set(value)) != len(value):
            raise ValueError("permissions must not contain duplicates")
        return value


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(min_length=1)
    package_manager: str = Field(min_length=1)
    build_cmd: str = Field(min_length=1)
    test_cmd: str = Field(min_length=1)
    run_cmd: str = Field(
        min_length=1,
        description=f"Command that starts the project; must contain {PORT_PLACEHOLDER}.",
    )
    port: int = Field(ge=1024, le=65535, description="Default port the project listens on.")
    roles: dict[RoleName, RoleConfig]

    @field_validator("run_cmd")
    @classmethod
    def _run_cmd_has_port(cls, value: str) -> str:
        if PORT_PLACEHOLDER not in value:
            raise ValueError(f"run_cmd must contain the {PORT_PLACEHOLDER} placeholder")
        return value

    @field_validator("roles")
    @classmethod
    def _all_roles_present(cls, value: dict[RoleName, RoleConfig]) -> dict[RoleName, RoleConfig]:
        missing = [r.value for r in RoleName if r not in value]
        if missing:
            raise ValueError(f"missing role configuration for: {', '.join(missing)}")
        return value


class ProfileValidationError(ValueError):
    """Raised when a profile cannot be read or fails validation, with a readable summary."""

    def __init__(self, message: str, errors: list[ErrorDetails] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []

    @classmethod
    def from_pydantic(cls, error: ValidationError) -> ProfileValidationError:
        errors = error.errors()
        lines = [f"invalid profile ({error.error_count()} error(s)):"]
        for err in errors:
            loc = ".".join(str(part) for part in err["loc"]) or "<root>"
            lines.append(f"  - {loc}: {err['msg']}")
        return cls("\n".join(lines), errors)


def parse_profile(data: dict[str, Any]) -> Profile:
    try:
        return Profile.model_validate(data)
    except ValidationError as exc:
        raise ProfileValidationError.from_pydantic(exc) from exc


def load_profile(path: Path) -> Profile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileValidationError(f"invalid profile: {path} is not valid JSON: {exc}") from exc
    return parse_profile(data)


def profile_json_schema() -> dict[str, Any]:
    return Profile.model_json_schema()


def export_json_schema(path: Path) -> None:
    path.write_text(json.dumps(profile_json_schema(), indent=2) + "\n", encoding="utf-8")
