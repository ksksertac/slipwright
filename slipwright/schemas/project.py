"""Project: a repository the user works on over time.

A project owns jobs ("developments"). It knows where the repository lives on disk, which
remote it came from (GitHub) and, optionally, which Jira project mirrors its work. The
optional ``profile`` is the seed profile jobs of this project start from; when it is
absent the engine's default seed applies.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from slipwright.schemas.job import new_job_id, utcnow
from slipwright.schemas.profile import Profile

_GITHUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


ReviewMode = Literal["off", "advisory", "blocking"]
Language = Literal["tr", "en"]
LANGUAGE_NAMES: dict[str, str] = {"tr": "Turkish", "en": "English"}
SprintMode = Literal["off", "active", "create"]
GateMode = Literal["manual", "assisted", "auto"]


class SupervisorSettings(BaseModel):
    """Who calls *approve* at the gates (T9.8). The gates themselves never change."""

    model_config = ConfigDict(extra="forbid")

    mode: GateMode = Field(
        default="assisted",
        description="manual: no supervisor; assisted: a recommendation next to the gate; "
        "auto: confident low-risk approvals are made for you.",
    )
    threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="Auto needs at least this.")
    cap: int = Field(default=3, ge=0, description="Automatic approvals per job.")
    allow_final_gate: bool = Field(
        default=False, description="Let auto approve the written tests (the PR gate)."
    )


class BudgetSettings(BaseModel):
    """Per-job limits (T9.7); None means unlimited. Exceeding one fails the job with the
    reason in its history."""

    model_config = ConfigDict(extra="forbid")

    max_tokens: int | None = Field(default=None, ge=1000)
    max_wall_clock_s: int | None = Field(default=None, ge=60)
    max_invocations: int | None = Field(default=None, ge=1)


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    repo_path: Path | None = Field(
        default=None, description="Local checkout; filled in after cloning when absent."
    )
    github_repo: str | None = Field(default=None, description="``owner/name`` on GitHub.")
    clone_url: str | None = Field(
        default=None,
        description="Where to clone from when repo_path is absent; derived from github_repo.",
    )
    jira_project_key: str | None = None
    language: Language = Field(
        default="tr",
        description="The language the agents write for people in: backlog titles and "
        "descriptions (and so Jira), plan summaries, test-case names, summaries.",
    )
    jira_transitions: dict[str, str] = Field(
        default_factory=dict,
        description="Task status -> Jira transition name (todo/in_progress/done/failed).",
    )
    jira_sprint: SprintMode = Field(
        default="create",
        description="Where mirrored stories go: off (backlog), active (the running sprint, "
        "else backlog) or create (the running sprint, else a new one named after the "
        "development, started for two weeks).",
    )
    profile: Profile | None = Field(default=None, description="Seed profile for new jobs.")
    review: ReviewMode = Field(
        default="advisory",
        description="Standards review after each phase: off, advisory (recorded, never "
        "blocks) or blocking (the specialist fixes, then a human gate).",
    )
    supervisor: SupervisorSettings = Field(default_factory=SupervisorSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("github_repo")
    @classmethod
    def _github_repo_shape(cls, value: str | None) -> str | None:
        if value is not None and not _GITHUB_REPO.match(value):
            raise ValueError("github_repo must look like owner/name")
        return value

    @field_validator("jira_project_key")
    @classmethod
    def _jira_key_shape(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip().upper()
            if not _JIRA_KEY.match(value):
                raise ValueError("jira_project_key must be an uppercase Jira project key")
        return value

    @property
    def effective_clone_url(self) -> str | None:
        if self.clone_url:
            return self.clone_url
        if self.github_repo:
            return f"https://github.com/{self.github_repo}.git"
        return None


class ProjectPatch(BaseModel):
    """Fields a client may change after creation. Unset fields are left alone."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    github_repo: str | None = None
    jira_project_key: str | None = None
    language: Language | None = None
    jira_transitions: dict[str, str] | None = None
    jira_sprint: SprintMode | None = None
    profile: Profile | None = None
    review: ReviewMode | None = None
    supervisor: SupervisorSettings | None = None
    budget: BudgetSettings | None = None


__all__ = [
    "LANGUAGE_NAMES",
    "BudgetSettings",
    "GateMode",
    "Language",
    "Project",
    "ProjectPatch",
    "ReviewMode",
    "SprintMode",
    "SupervisorSettings",
]
