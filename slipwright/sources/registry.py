"""The known source hosts and how to build a client for one.

Adding a host is one ``SourceSpec`` plus a class that satisfies ``SourceHost``; nothing
else in the engine or the UI names a vendor. Credentials come from the settings store
(encrypted) or, failing that, the host's environment variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from slipwright.githost import CiStatus

GITHUB = "github"
BITBUCKET = "bitbucket"


class SourceError(RuntimeError):
    """The host refused or could not be reached; the message is shown to the person."""


class Identity(BaseModel):
    """Who the stored token belongs to, as the settings page shows it."""

    model_config = ConfigDict(extra="forbid")

    login: str
    name: str | None = None
    # what is left of the host's rate limit, when it reports one
    rate_limit_remaining: int | None = None
    rate_limit_limit: int | None = None


class Repo(BaseModel):
    """One repository the token can see."""

    model_config = ConfigDict(extra="forbid")

    full_name: str  # owner/name on GitHub, workspace/repo on Bitbucket
    private: bool = False
    default_branch: str = "main"
    html_url: str = ""
    description: str | None = None


class SourceCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    token: str
    api_url: str
    # the account or workspace new projects default to
    owner: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    """What the settings page needs to describe a host, and what a client needs to talk
    to it."""

    name: str
    label: str
    env_var: str
    default_api_url: str
    clone_host: str  # where https clone URLs point
    token_label: str  # what the host calls the secret
    token_docs_url: str
    owner_label: str  # "owner / organisation" vs "workspace"
    # the username git uses with the token in an https URL
    push_user: str


SOURCES: dict[str, SourceSpec] = {
    GITHUB: SourceSpec(
        name=GITHUB,
        label="GitHub",
        env_var="GITHUB_TOKEN",
        default_api_url="https://api.github.com",
        clone_host="github.com",
        token_label="Personal access token",
        token_docs_url="https://github.com/settings/tokens",
        owner_label="Owner / organisation",
        push_user="x-access-token",
    ),
    BITBUCKET: SourceSpec(
        name=BITBUCKET,
        label="Bitbucket",
        env_var="BITBUCKET_TOKEN",
        default_api_url="https://api.bitbucket.org/2.0",
        clone_host="bitbucket.org",
        token_label="Workspace or repository access token",
        token_docs_url="https://support.atlassian.com/bitbucket-cloud/docs/access-tokens/",
        owner_label="Workspace",
        push_user="x-token-auth",
    ),
}


class SourceHost(Protocol):
    """Everything the engine asks of a hosting service."""

    def whoami(self) -> Identity: ...

    def list_repos(self, *, limit: int = 300) -> list[Repo]: ...

    def create_repo(self, name: str, *, private: bool = True, description: str = "") -> Repo:
        """Open a new repository on the host and return it, ready to clone."""
        ...

    def clone_url(self, full_name: str) -> str: ...

    def authenticated_url(self, url: str) -> str:
        """The clone URL with the token in it, for a private repository."""
        ...

    def push(self, worktree: Path, branch: str) -> None: ...

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str: ...

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus: ...


def source_names() -> list[str]:
    return list(SOURCES)


def build_host(
    creds: SourceCredentials,
    *,
    transport: httpx.BaseTransport | None = None,
    base_branch: str = "main",
) -> SourceHost:
    spec = SOURCES.get(creds.name)
    if spec is None:
        raise SourceError(f"unknown source: {creds.name}")
    if creds.name == GITHUB:
        from slipwright.sources.github import GitHubHost

        return GitHubHost(creds, spec, transport=transport, base_branch=base_branch)
    from slipwright.sources.bitbucket import BitbucketHost

    return BitbucketHost(creds, spec, transport=transport, base_branch=base_branch)


class SourceSettings(BaseModel):
    """One row of the sources page. The token itself is never returned."""

    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    token_label: str
    token_docs_url: str
    owner_label: str
    default_api_url: str
    api_url: str | None = None
    env_var: str
    owner: str | None = None
    base_branch: str = "main"
    token_set: bool = False
    token_hint: str | None = Field(default=None, description="Last four characters, if set.")
    token_from_env: bool = False
    is_default: bool = False


__all__ = [
    "BITBUCKET",
    "GITHUB",
    "SOURCES",
    "Identity",
    "Repo",
    "SourceCredentials",
    "SourceError",
    "SourceHost",
    "SourceSettings",
    "SourceSpec",
    "build_host",
    "source_names",
]
