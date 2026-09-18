"""Settings endpoints: the GitHub and Jira connections.

Reads are open to any logged-in user; writes and connection tests are admin only. A
stored token is never returned, only whether one exists and its last four characters.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from slipwright.api.auth import require_admin
from slipwright.engine import Engine
from slipwright.github import GitHubError, GitHubIdentity, GitHubRepo, GitHubSettings
from slipwright.jira import JiraAccount, JiraError, JiraProject, JiraSettings
from slipwright.providers import ProviderError
from slipwright.providers.registry import PROVIDERS
from slipwright.schemas.profile import Profile
from slipwright.standards.editing import PageError, PageInfo
from slipwright.standards.index import StandardsIndexError
from slipwright.store import ProjectNotFound

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


class ProviderSettings(BaseModel):
    name: str
    label: str
    env_var: str
    docs_url: str
    default_base_url: str
    base_url: str | None = None
    key_set: bool
    key_hint: str | None = None
    key_from_env: bool
    is_default: bool
    default_model: str | None = Field(
        default=None, description="What roles without a provider of their own run on here."
    )
    max_tokens: int | None = Field(default=None, description="Output limit override.")
    default_max_tokens: int = Field(description="The vendor's default output limit.")


class ProviderSettingsIn(BaseModel):
    api_key: str | None = Field(default=None, description="Omit to keep the stored key.")
    base_url: str | None = Field(default=None, description="Override the vendor URL.")
    clear_key: bool = False
    make_default: bool = False
    default_model: str | None = Field(default=None, description="Empty string clears it.")
    max_tokens: int | None = Field(
        default=None, ge=0, le=200_000, description="Largest answer per call; 0 = vendor default."
    )


class ProviderModels(BaseModel):
    name: str
    models: list[str]


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


# -- model providers ---------------------------------------------------------------------------


@router.get("/settings/providers", response_model=list[ProviderSettings])
def get_providers(request: Request) -> list[ProviderSettings]:
    """Every known model provider with whether a key is set (never the key itself)."""
    return [ProviderSettings(**p) for p in _engine(request).provider_settings()]


def _provider_name(name: str) -> str:
    if name not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider: {name}")
    return name


@router.put("/settings/providers/{name}", response_model=list[ProviderSettings])
def put_provider(name: str, body: ProviderSettingsIn, request: Request) -> list[ProviderSettings]:
    require_admin(request)
    eng = _engine(request)
    eng.update_provider_settings(_provider_name(name), **body.model_dump())
    return [ProviderSettings(**p) for p in eng.provider_settings()]


@router.post("/settings/providers/{name}/test", response_model=ProviderModels)
def test_provider(name: str, request: Request) -> ProviderModels:
    """Call the vendor with the stored key and return the models it can use."""
    require_admin(request)
    return provider_models(name, request)


@router.get("/settings/providers/{name}/models", response_model=ProviderModels)
def provider_models(name: str, request: Request) -> ProviderModels:
    eng = _engine(request)
    try:
        return ProviderModels(name=name, models=eng.provider_models(_provider_name(name)))
    except ProviderError as exc:
        status = 400 if "no API key" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# -- standards (RAG) ---------------------------------------------------------------------------


class StandardsSettings(BaseModel):
    embedder: str
    embedding_model: str
    local_model: str
    top_k: int
    token_budget: int


class StandardsSettingsIn(BaseModel):
    embedder: str | None = Field(default=None, description="none | openai | local | hashing")
    embedding_model: str | None = None
    local_model: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    token_budget: int | None = Field(default=None, ge=200, le=20000)


class StandardsStatus(BaseModel):
    settings: StandardsSettings
    chunks: int
    embedded: int
    per_domain: dict[str, int]


class StandardsHit(BaseModel):
    id: str
    domain: str
    page: str
    heading: str
    text: str
    scope: str
    score: float
    keyword: float
    semantic: float


@router.get("/settings/standards", response_model=StandardsStatus)
def get_standards(request: Request) -> StandardsStatus:
    eng = _engine(request)
    eng.ensure_standards_indexed()
    stats = eng.standards_index.stats()
    return StandardsStatus(
        settings=StandardsSettings(**eng.standards_settings()),
        chunks=stats["chunks"],
        embedded=stats["embedded"],
        per_domain=stats["per_domain"],
    )


@router.put("/settings/standards", response_model=StandardsSettings)
def put_standards(body: StandardsSettingsIn, request: Request) -> StandardsSettings:
    require_admin(request)
    if body.embedder is not None and body.embedder not in ("none", "openai", "local", "hashing"):
        raise HTTPException(
            status_code=400, detail="embedder must be none, openai, local or hashing"
        )
    return StandardsSettings(**_engine(request).update_standards_settings(**body.model_dump()))


@router.post("/settings/standards/reindex", response_model=StandardsStatus)
def reindex_standards(request: Request, project_id: str | None = None) -> StandardsStatus:
    require_admin(request)
    eng = _engine(request)
    try:
        eng.reindex_standards(None, force=True)
        if project_id:
            eng.reindex_standards(project_id, force=True)
        else:
            for project in eng.store.list_projects():
                eng.reindex_standards(project.id, force=True)
    except StandardsIndexError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return get_standards(request)


@router.get("/settings/standards/search", response_model=list[StandardsHit])
def search_standards(
    request: Request, q: str, domain: str | None = None, project_id: str | None = None, k: int = 4
) -> list[StandardsHit]:
    """Try a query the way the agents do: ranked sections with their scores."""
    eng = _engine(request)
    try:
        hits = eng.search_standards(q, domain, project_id=project_id, k=k)
    except StandardsIndexError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        StandardsHit(
            id=h.chunk.id,
            domain=h.chunk.domain,
            page=h.chunk.page,
            heading=f"{h.chunk.title} — {h.chunk.heading}",
            text=h.chunk.text,
            scope=h.chunk.scope,
            score=round(h.score, 3),
            keyword=round(h.keyword, 3),
            semantic=round(h.semantic, 3),
        )
        for h in hits
    ]


# -- Jira ------------------------------------------------------------------------------------


@router.get("/settings/jira", response_model=JiraSettings)
def get_jira(request: Request) -> JiraSettings:
    return _engine(request).jira_settings()


@router.put("/settings/jira", response_model=JiraSettings)
def put_jira(body: JiraSettingsIn, request: Request) -> JiraSettings:
    require_admin(request)
    return _engine(request).update_jira_settings(**body.model_dump())


class JiraSweep(BaseModel):
    jobs: int
    updated: int
    errors: int
    at: datetime


@router.get("/settings/jira/sweep", response_model=JiraSweep | None)
def last_jira_sweep(request: Request) -> JiraSweep | None:
    data = _engine(request).store.get_setting("jira.last_sweep")
    return JiraSweep(**data) if data else None


@router.post("/settings/jira/sweep", response_model=JiraSweep)
def run_jira_sweep(request: Request) -> JiraSweep:
    """Run the PO's round now: complete missing issues and sprints for every job."""
    require_admin(request)
    return JiraSweep(**_engine(request).jira_sweep())


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


__all__ = [
    "GitHubSettingsIn",
    "JiraSettingsIn",
    "JiraTestResult",
    "ProviderModels",
    "ProviderSettings",
    "ProviderSettingsIn",
    "router",
]


# -- standards pages (T9.6) --------------------------------------------------------------------


class StandardsPage(BaseModel):
    path: str
    domain: str
    title: str
    scope: str
    sections: int
    words: int
    modified_at: datetime


class StandardsPageText(StandardsPage):
    text: str


class PageWrite(BaseModel):
    text: str = Field(min_length=1)
    project_id: str | None = None


class PageCreate(BaseModel):
    domain: str
    title: str = Field(min_length=1)
    text: str = ""
    project_id: str | None = None


def _page(info: PageInfo) -> StandardsPage:
    return StandardsPage(
        path=info.path,
        domain=info.domain,
        title=info.title,
        scope=info.scope,
        sections=info.sections,
        words=info.words,
        modified_at=info.modified_at,
    )


def _repo(eng: Engine, project_id: str | None) -> Path | None:
    try:
        return eng.standards_repo_for(project_id)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=f"no project {project_id}") from exc


@router.get("/standards/pages", response_model=list[StandardsPage])
def list_standards_pages(
    request: Request, domain: str | None = None, project_id: str | None = None
) -> list[StandardsPage]:
    """The pages of a domain (plus ``core.md``) in the global corpus or a project's overrides."""
    eng = _engine(request)
    pages = eng.standards_editor.list_pages(_repo(eng, project_id), domain)
    return [_page(p) for p in pages]


@router.get("/standards/pages/{path:path}", response_model=StandardsPageText)
def get_standards_page(
    path: str, request: Request, project_id: str | None = None
) -> StandardsPageText:
    eng = _engine(request)
    repo = _repo(eng, project_id)
    try:
        text = eng.standards_editor.read(path, repo)
    except PageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no page {path}") from exc
    info = next(p for p in eng.standards_editor.list_pages(repo) if p.path == path)
    return StandardsPageText(text=text, **_page(info).model_dump())


@router.put("/standards/pages/{path:path}", response_model=StandardsPage)
def put_standards_page(path: str, body: PageWrite, request: Request) -> StandardsPage:
    """Save a page (linted first), commit it on the review branch, reindex."""
    user = require_admin(request)
    eng = _engine(request)
    repo = _repo(eng, body.project_id)
    try:
        info = eng.standards_editor.write(path, body.text, repo, author=user.username)
    except PageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    eng.ensure_standards_indexed(body.project_id)
    return _page(info)


@router.post("/standards/pages", response_model=StandardsPage, status_code=201)
def create_standards_page(body: PageCreate, request: Request) -> StandardsPage:
    user = require_admin(request)
    eng = _engine(request)
    repo = _repo(eng, body.project_id)
    try:
        info = eng.standards_editor.create(
            body.domain, body.title, body.text, repo, author=user.username
        )
    except PageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    eng.ensure_standards_indexed(body.project_id)
    return _page(info)


@router.delete("/standards/pages/{path:path}", status_code=204)
def delete_standards_page(path: str, request: Request, project_id: str | None = None) -> None:
    user = require_admin(request)
    eng = _engine(request)
    repo = _repo(eng, project_id)
    try:
        eng.standards_editor.delete(path, repo, author=user.username)
    except PageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no page {path}") from exc
    eng.ensure_standards_indexed(project_id)


# -- notifications (T9.8) ----------------------------------------------------------------------


class NotificationSettings(BaseModel):
    webhook_url: str | None = Field(
        default=None, description="POSTed a JSON event on every automatic approval."
    )


@router.get("/settings/notifications", response_model=NotificationSettings)
def get_notifications(request: Request) -> NotificationSettings:
    eng = _engine(request)
    return NotificationSettings(webhook_url=eng.store.get_setting("notifications.webhook_url"))


@router.put("/settings/notifications", response_model=NotificationSettings)
def put_notifications(body: NotificationSettings, request: Request) -> NotificationSettings:
    require_admin(request)
    eng = _engine(request)
    url = (body.webhook_url or "").strip() or None
    if url and not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="webhook_url must be http(s)")
    eng.store.set_setting("notifications.webhook_url", url)
    return NotificationSettings(webhook_url=url)
