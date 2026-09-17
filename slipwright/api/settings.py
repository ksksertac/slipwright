"""Settings endpoints: the GitHub and Jira connections.

Reads are open to any logged-in user; writes and connection tests are admin only. A
stored token is never returned, only whether one exists and its last four characters.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slipwright.api.auth import require_admin
from slipwright.engine import Engine
from slipwright.github import GitHubError, GitHubIdentity, GitHubRepo, GitHubSettings
from slipwright.jira import JiraAccount, JiraError, JiraProject, JiraSettings
from slipwright.schemas.profile import Profile

router = APIRouter(tags=["settings"])


class GitHubSettingsIn(BaseModel):
    token: str | None = Field(default=None, description="Omit to keep the stored token.")
    owner: str | None = None
    base_branch: str | None = None
    clear_token: bool = False


class JiraSettingsIn(BaseModel):
    site_url: str | None = None
    email: str | None = None
    token: str | None = Field(default=None, description="Omit to keep the stored token.")
    clear_token: bool = False
    issue_types: dict[str, str] | None = None
    agent_email: str | None = None
    agent_token: str | None = None
    clear_agent_token: bool = False


class JiraTestResult(BaseModel):
    account: JiraAccount
    agent_account: JiraAccount | None = None
    projects: list[JiraProject]


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


@router.get("/settings/profile", response_model=Profile)
def default_profile(request: Request) -> Profile:
    """The engine's default seed profile: what a project without its own starts from."""
    return _engine(request).seed_profile


# -- Jira ------------------------------------------------------------------------------------


@router.get("/settings/jira", response_model=JiraSettings)
def get_jira(request: Request) -> JiraSettings:
    return _engine(request).jira_settings()


@router.put("/settings/jira", response_model=JiraSettings)
def put_jira(body: JiraSettingsIn, request: Request) -> JiraSettings:
    require_admin(request)
    return _engine(request).update_jira_settings(**body.model_dump())


@router.post("/settings/jira/test", response_model=JiraTestResult)
def test_jira(request: Request) -> JiraTestResult:
    """Call Jira with the stored credentials (and the agent account when set)."""
    require_admin(request)
    eng = _engine(request)
    try:
        client = eng.jira_client()
    except JiraError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        account = client.myself()
        projects = client.list_projects()
        agent = None
        if eng.jira_settings().agent_token_set:
            agent = eng.jira_client(agent=True).myself()
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JiraTestResult(account=account, agent_account=agent, projects=projects)


@router.get("/settings/jira/projects", response_model=list[JiraProject])
def jira_projects(request: Request) -> list[JiraProject]:
    eng = _engine(request)
    try:
        return eng.jira_client().list_projects()
    except JiraError as exc:
        status = 400 if "not configured" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


__all__ = ["GitHubSettingsIn", "JiraSettingsIn", "JiraTestResult", "router"]
