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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from slipwright.schemas.job import new_job_id, utcnow
from slipwright.schemas.profile import Profile

_GITHUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


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
    jira_transitions: dict[str, str] = Field(
        default_factory=dict,
        description="Task status -> Jira transition name (todo/in_progress/done/failed).",
    )
    profile: Profile | None = Field(default=None, description="Seed profile for new jobs.")
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
    jira_transitions: dict[str, str] | None = None
    profile: Profile | None = None


__all__ = ["Project", "ProjectPatch"]
