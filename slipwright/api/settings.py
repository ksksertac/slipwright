"""Settings endpoints: the GitHub connection (Jira follows in T7.4).

Reads are open to any logged-in user; writes and connection tests are admin only. A
stored token is never returned, only whether one exists and its last four characters.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slipwright.api.auth import require_admin
from slipwright.engine import Engine
from slipwright.github import GitHubError, GitHubIdentity, GitHubRepo, GitHubSettings

router = APIRouter(tags=["settings"])


class GitHubSettingsIn(BaseModel):
    token: str | None = Field(default=None, description="Omit to keep the stored token.")
    owner: str | None = None
    base_branch: str | None = None
    clear_token: bool = False


def _engine(request: Request) -> Engine:
    eng: Engine = request.app.state.engine
    return eng


@router.get("/settings/github", response_model=GitHubSettings)
def get_github(request: Request) -> GitHubSettings:
    return _engine(request).github_settings()


@router.put("/settings/github", response_model=GitHubSettings)
def put_github(body: GitHubSettingsIn, request: Request) -> GitHubSettings:
    require_admin(request)
    return _engine(request).update_github_settings(
        token=body.token,
        owner=body.owner,
        base_branch=body.base_branch,
        clear_token=body.clear_token,
    )


@router.post("/settings/github/test", response_model=GitHubIdentity)
def test_github(request: Request) -> GitHubIdentity:
    """Call GitHub with the stored token; 400 when none is stored, 502 when it fails."""
    require_admin(request)
    eng = _engine(request)
    try:
        client = eng.github_client()
    except GitHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return client.whoami()
    except GitHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/settings/github/repos", response_model=list[GitHubRepo])
def github_repos(request: Request) -> list[GitHubRepo]:
    eng = _engine(request)
    try:
        return eng.github_client().list_repos()
    except GitHubError as exc:
        status = 400 if "no GitHub token" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


__all__ = ["GitHubSettingsIn", "router"]
