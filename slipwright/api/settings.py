"""Settings endpoints: model providers, code hosts, Jira, standards and prices.

Two kinds of setting live here and they are governed differently.

**A person's own** -- model API keys, Git host tokens, the Jira connection, which model
each of their agents runs on. Any signed-in account reads and writes its own, because on
a hosted installation everybody brings their own keys and nobody should need an
administrator to enter one. ``_engine`` binds every call below to the caller.

**The installation's** -- what models cost, how the shared standards index is built, the
sender mail goes out from, where webhooks are posted. Those stay admin-only, and
``store/scoped.py`` routes them to the installation whichever account asks.

A stored secret is never returned either way: only whether one exists, and its last four
characters.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from slipwright import prices
from slipwright.api.auth import require_admin, require_owner
from slipwright.engine import Engine
from slipwright.github import GitHubError, GitHubIdentity, GitHubRepo, GitHubSettings
from slipwright.jira import JiraAccount, JiraError, JiraProject, JiraSettings
from slipwright.mail import read_outbox
from slipwright.providers import ProviderError
from slipwright.providers.registry import PROVIDERS
from slipwright.schemas.profile import Profile
from slipwright.sources import SOURCES, Identity, Repo, SourceError
from slipwright.sources.registry import SourceSettings
from slipwright.standards.editing import PageError, PageInfo, Rule
from slipwright.standards.index import StandardsIndexError
from slipwright.store import ANY_OWNER, ProjectNotFound
from slipwright.support import SupportError

router = APIRouter(tags=["settings"])

#: Loose on purpose: the strict check is ``slipwright.auth.normalise_email`` at the point
#: of sending. This only stops an obvious typo being saved as the sender.
_EMAIL_ISH = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    """The engine bound to whoever is asking.

    Every settings page below reads and writes through this, so a model key, a Git token
    or a Jira connection entered here belongs to that account and to nobody else. The
    settings that are the server's rather than a person's -- mail, prices, webhooks, how
    the standards index is built -- are routed back to the installation by
    ``store/scoped.py`` whatever engine they are asked of, so the admin-only endpoints
    below still see and change exactly what they always did.

    Somebody on a team is bound to the account that invited them (``tenant_id``), because
    the settings they are allowed to look at -- which model an agent runs on, the team's
    standards -- are the ones their work actually runs under. What they may *change* is
    decided by the guards on each endpoint, not here.
    """
    eng: Engine = request.app.state.engine
    user = getattr(request.state, "user", None)
    if user is None or user.id == "anonymous":
        return eng
    return eng.for_user(str(user.tenant_id))


class SourceSettingsIn(BaseModel):
    """What the sources page may change. An omitted token keeps the stored one."""

    model_config = ConfigDict(extra="forbid")

    token: str | None = None
    owner: str | None = None
    base_branch: str | None = None
    api_url: str | None = None
    clear_token: bool = False
    make_default: bool = False


@router.get("/settings/sources", response_model=list[SourceSettings])
def get_sources(request: Request) -> list[SourceSettings]:
    """Every known host: whether it is connected, where it points, which is the default."""
    return _engine(request).source_settings()


@router.put("/settings/sources/{name}", response_model=list[SourceSettings])
def put_source(name: str, body: SourceSettingsIn, request: Request) -> list[SourceSettings]:
    require_owner(request)
    try:
        return _engine(request).update_source_settings(
            name,
            token=body.token,
            owner=body.owner,
            base_branch=body.base_branch,
            api_url=body.api_url,
            clear_token=body.clear_token,
            make_default=body.make_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/settings/sources/{name}/test", response_model=Identity)
def test_source(name: str, request: Request) -> Identity:
    """Ask the host who the stored token belongs to: 400 without a token, 502 when the
    host refuses it."""
    require_owner(request)
    eng = _engine(request)
    if name not in SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown source: {name}")
    try:
        host = eng.source_host(name)
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return host.whoami()
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class NewRepo(BaseModel):
    """Open a repository on the host, for a project that starts from nothing."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    private: bool = True
    description: str = ""


@router.post("/settings/sources/{name}/repos", response_model=Repo, status_code=201)
def create_source_repo(name: str, body: NewRepo, request: Request) -> Repo:
    """Open a repository on the host and hand it back, ready for a project to clone."""
    require_owner(request)
    eng = _engine(request)
    if name not in SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown source: {name}")
    try:
        return eng.source_host(name).create_repo(
            body.name.strip(), private=body.private, description=body.description.strip()
        )
    except SourceError as exc:
        status = 400 if "no token" in str(exc) or "workspace" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/settings/sources/{name}/repos", response_model=list[Repo])
def source_repos(name: str, request: Request) -> list[Repo]:
    """The repositories that host's token can see, for the new-project picker."""
    eng = _engine(request)
    if name not in SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown source: {name}")
    try:
        return eng.source_host(name).list_repos()
    except SourceError as exc:
        status = 400 if "no token" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/settings/github", response_model=GitHubSettings)
def get_github(request: Request) -> GitHubSettings:
    return _engine(request).github_settings()


@router.put("/settings/github", response_model=GitHubSettings)
def put_github(body: GitHubSettingsIn, request: Request) -> GitHubSettings:
    require_owner(request)
    return _engine(request).update_github_settings(
        token=body.token,
        owner=body.owner,
        base_branch=body.base_branch,
        clear_token=body.clear_token,
    )


@router.post("/settings/github/test", response_model=GitHubIdentity)
def test_github(request: Request) -> GitHubIdentity:
    """Call GitHub with the stored token; 400 when none is stored, 502 when it fails."""
    require_owner(request)
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


# -- what one account may take of a shared machine ------------------------------------------


class QuotaSettings(BaseModel):
    """The limits in force. ``0`` means no limit, which is what a local install wants."""

    max_running_jobs: int = Field(ge=0, description="Developments running at once.")
    max_projects: int = Field(ge=0, description="Projects, not counting the example.")
    max_disk_mb: int = Field(ge=0, description="Checkouts and clones together.")


class QuotaSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_running_jobs: int | None = Field(default=None, ge=0)
    max_projects: int | None = Field(default=None, ge=0)
    max_disk_mb: int | None = Field(default=None, ge=0)


class QuotaUsage(BaseModel):
    """What this account is using, and what it is allowed."""

    running_jobs: int
    projects: int
    disk_mb: int
    limits: QuotaSettings


@router.get("/quota", response_model=QuotaUsage)
def get_quota(request: Request) -> QuotaUsage:
    """What you are using of the server, and where the line is."""
    eng = _engine(request)
    owner = _caller(request)
    use = eng.quotas.usage(owner)
    return QuotaUsage(
        running_jobs=use.running_jobs,
        projects=use.projects,
        disk_mb=use.disk_mb,
        limits=QuotaSettings(**vars(eng.quotas.limits())),
    )


@router.put("/settings/quota", response_model=QuotaSettings)
def put_quota(body: QuotaSettingsIn, request: Request) -> QuotaSettings:
    """Raise or lower the limits. The server's own decision, so administrators only."""
    require_admin(request)
    changed = _engine(request).quotas.update(
        **{k: v for k, v in body.model_dump().items() if v is not None}
    )
    return QuotaSettings(**vars(changed))


# -- getting started ---------------------------------------------------------------------


class OnboardingStep(BaseModel):
    """One thing a new account has to do before an agent can run for them."""

    key: str
    done: bool
    required: bool = True


class Onboarding(BaseModel):
    """What is still missing, and whether to keep saying so.

    Deliberately *derived* rather than stored: a stored checklist drifts from the truth
    the moment somebody removes a key, and then the dashboard is lying. The only thing
    kept is whether the person has dismissed it.
    """

    steps: list[OnboardingStep]
    done: bool
    dismissed: bool

    @property
    def ready(self) -> bool:
        return all(s.done for s in self.steps if s.required)


class Dismiss(BaseModel):
    dismissed: bool = True


def _onboarding(request: Request) -> Onboarding:
    eng = _engine(request)
    has_key = any(p["key_set"] for p in eng.provider_settings())
    has_host = any(s.token_set for s in eng.source_settings())
    # the same scope the settings above are read in: somebody on a team is getting the
    # account that invited them set up, not an account of their own
    user = getattr(request.state, "user", None)
    tenant = ANY_OWNER if user is None or user.id == "anonymous" else str(user.tenant_id)
    has_project = any(not p.is_demo for p in eng.store.list_projects(tenant))
    steps = [
        OnboardingStep(key="model", done=has_key),
        OnboardingStep(key="source", done=has_host),
        # Jira is genuinely optional: plenty of people do not use it at all
        OnboardingStep(key="jira", done=eng.jira_settings().configured, required=False),
        OnboardingStep(key="project", done=has_project),
    ]
    made = Onboarding(
        steps=steps,
        done=False,
        dismissed=bool(eng.store.get_setting("onboarding.dismissed")),
    )
    return made.model_copy(update={"done": made.ready})


@router.get("/onboarding", response_model=Onboarding)
def get_onboarding(request: Request) -> Onboarding:
    """What this account still has to connect before it can start work."""
    return _onboarding(request)


@router.put("/onboarding", response_model=Onboarding)
def put_onboarding(body: Dismiss, request: Request) -> Onboarding:
    """Stop showing the checklist -- or show it again."""
    _engine(request).store.set_setting("onboarding.dismissed", body.dismissed)
    return _onboarding(request)


def _provider_name(name: str) -> str:
    if name not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider: {name}")
    return name


@router.put("/settings/providers/{name}", response_model=list[ProviderSettings])
def put_provider(name: str, body: ProviderSettingsIn, request: Request) -> list[ProviderSettings]:
    require_owner(request)
    eng = _engine(request)
    eng.update_provider_settings(_provider_name(name), **body.model_dump())
    return [ProviderSettings(**p) for p in eng.provider_settings()]


@router.post("/settings/providers/{name}/test", response_model=ProviderModels)
def test_provider(name: str, request: Request) -> ProviderModels:
    """Call the vendor with the stored key and return the models it can use."""
    require_owner(request)
    return provider_models(name, request)


@router.get("/settings/providers/{name}/models", response_model=ProviderModels)
def provider_models(name: str, request: Request) -> ProviderModels:
    eng = _engine(request)
    try:
        return ProviderModels(name=name, models=eng.provider_models(_provider_name(name)))
    except ProviderError as exc:
        status = 400 if "no API key" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# -- model prices ------------------------------------------------------------------------------
# No vendor publishes a pricing API, so the figures come from a published table fetched
# daily (slipwright/prices.py). A price typed in here is marked `manual` and the daily
# fetch never overwrites it, which is how an installation with its own rates keeps them.


class ModelPrice(BaseModel):
    provider: str
    model: str
    input_usd: float = Field(description="US dollars per 1M input tokens.")
    output_usd: float = Field(description="US dollars per 1M output tokens.")
    source: str
    at: datetime


class ModelPrices(BaseModel):
    prices: list[ModelPrice]
    last_fetch: datetime | None = None
    rows: int | None = Field(default=None, description="Rows written by the last fetch.")
    source_url: str | None = None


class ModelPriceIn(BaseModel):
    input_usd: float = Field(ge=0)
    output_usd: float = Field(ge=0)


@router.get("/settings/prices", response_model=ModelPrices)
def list_model_prices(request: Request, provider: str | None = None) -> ModelPrices:
    """Every stored price, newest fetch first in the header."""
    eng = _engine(request)
    last = eng.store.get_setting("prices.last_fetch", {}) or {}
    return ModelPrices(
        prices=[ModelPrice(**row) for row in eng.store.list_prices(provider)],
        last_fetch=last.get("at"),
        rows=last.get("rows"),
        source_url=last.get("source") or prices.SOURCE_URL,
    )


@router.post("/settings/prices/refresh", response_model=ModelPrices)
def refresh_model_prices(request: Request) -> ModelPrices:
    """Fetch the published table now instead of waiting for the daily run."""
    require_admin(request)
    eng = _engine(request)
    try:
        eng.refresh_prices()
    except prices.PriceFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return list_model_prices(request)


@router.put("/settings/prices/{provider}/{model:path}", response_model=ModelPrice)
def set_model_price(provider: str, model: str, body: ModelPriceIn, request: Request) -> ModelPrice:
    """Enter a rate by hand. It is kept through every later fetch until it is deleted."""
    require_admin(request)
    eng = _engine(request)
    eng.store.put_price(
        provider, model, input_usd=body.input_usd, output_usd=body.output_usd, source="manual"
    )
    row = eng.store.get_price(provider, model)
    assert row is not None
    return ModelPrice(**row)


@router.delete("/settings/prices/{provider}/{model:path}", status_code=204)
def delete_model_price(provider: str, model: str, request: Request) -> None:
    """Drop a hand-entered rate; the next fetch puts the published one back."""
    require_admin(request)
    _engine(request).store.delete_price(provider, model)


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
    require_owner(request)
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
    require_owner(request)
    return JiraSweep(**_engine(request).jira_sweep())


@router.post("/settings/jira/test", response_model=JiraTestResult)
def test_jira(request: Request) -> JiraTestResult:
    """Call Jira with the stored credentials (and the agent account when set)."""
    require_owner(request)
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


class NewJiraProject(BaseModel):
    """Open a Scrum project on the connected Jira rather than picking an existing one."""

    key: str = Field(min_length=2, max_length=10)
    name: str = Field(min_length=1)


@router.post("/settings/jira/projects", response_model=JiraProject, status_code=201)
def create_jira_project(body: NewJiraProject, request: Request) -> JiraProject:
    """Create the project the new-project page asked for, led by the connected account."""
    require_admin(request)
    eng = _engine(request)
    try:
        return eng.jira_client().create_project(body.key, body.name)
    except JiraError as exc:
        status = 400 if "not configured" in str(exc) or "usable" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


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


class StandardsRule(BaseModel):
    id: str
    path: str
    domain: str
    scope: str
    heading: str
    text: str
    words: int
    modified_at: datetime


class RuleWrite(BaseModel):
    heading: str = Field(min_length=1)
    text: str = Field(min_length=1)
    project_id: str | None = None


class RuleCreate(RuleWrite):
    domain: str


def _rule(rule: Rule) -> StandardsRule:
    return StandardsRule(**{k: getattr(rule, k) for k in StandardsRule.model_fields})


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


def _caller(request: Request) -> str | None:
    """Whose copy of a page is being edited. ``None`` is the installation's own files,
    which is what a local install and the CLI still write."""
    user = getattr(request.state, "user", None)
    if user is None or user.id == "anonymous":
        return None
    return str(user.id)


def _split(path: str) -> tuple[str, str]:
    """``backend/services-and-apis.md`` -> ``("backend", "services-and-apis")``."""
    head, _, tail = path.partition("/")
    if not tail:
        raise HTTPException(status_code=400, detail=f"not a page path: {path}")
    name = tail[:-3] if tail.endswith(".md") else tail
    return head, name


@router.put("/standards/pages/{path:path}", response_model=StandardsPage)
def put_standards_page(path: str, body: PageWrite, request: Request) -> StandardsPage:
    """Save a page.

    On a hosted installation this writes *your* copy: it shadows the page Slipwright
    ships, for your agents only, and the shipped file is never touched. A project
    override (``project_id``) still writes into that repository, because that is a
    property of the code rather than of a person. A local install with no accounts
    keeps writing the files and committing them on the review branch, as before.
    """
    eng = _engine(request)
    owner = _caller(request)
    if body.project_id is not None or owner is None:
        user = require_admin(request)
        repo = _repo(eng, body.project_id)
        try:
            info = eng.standards_editor.write(path, body.text, repo, author=user.username)
        except PageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        eng.ensure_standards_indexed(body.project_id)
        return _page(info)

    domain, name = _split(path)
    try:
        eng.standards_editor.check_text(body.text, domain=domain)
    except PageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    eng.raw_store.save_user_page(owner, domain, name, body.text)
    eng.reindex_standards(owner_id=owner, force=True)
    return _page(eng.standards_editor.describe(path, body.text, scope="user"))


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
    """Drop your copy of a page: it goes back to the one Slipwright ships.

    Deleting is therefore never destructive -- the default is always underneath.
    """
    eng = _engine(request)
    owner = _caller(request)
    if project_id is not None or owner is None:
        user = require_admin(request)
        repo = _repo(eng, project_id)
        try:
            eng.standards_editor.delete(path, repo, author=user.username)
        except PageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"no page {path}") from exc
        eng.ensure_standards_indexed(project_id)
        return

    domain, name = _split(path)
    if not eng.raw_store.delete_user_page(owner, domain, name):
        raise HTTPException(status_code=404, detail=f"you have no copy of {path}")
    eng.reindex_standards(owner_id=owner, force=True)


# -- standards rules: one "##" section each, the list an agent's page shows -------------------


@router.get("/standards/rules", response_model=list[StandardsRule])
def list_standards_rules(
    request: Request, domain: str, project_id: str | None = None
) -> list[StandardsRule]:
    """The domain's rules, flat, in the global corpus or a project's overrides."""
    eng = _engine(request)
    return [_rule(r) for r in eng.standards_editor.list_rules(_repo(eng, project_id), domain)]


@router.post("/standards/rules", response_model=StandardsRule, status_code=201)
def create_standards_rule(body: RuleCreate, request: Request) -> StandardsRule:
    user = require_admin(request)
    eng = _engine(request)
    repo = _repo(eng, body.project_id)
    try:
        rule = eng.standards_editor.add_rule(
            body.domain, body.heading, body.text, repo, author=user.username
        )
    except PageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    eng.ensure_standards_indexed(body.project_id)
    return _rule(rule)


@router.put("/standards/rules/{rule_id:path}", response_model=StandardsRule)
def put_standards_rule(rule_id: str, body: RuleWrite, request: Request) -> StandardsRule:
    user = require_admin(request)
    eng = _engine(request)
    repo = _repo(eng, body.project_id)
    try:
        rule = eng.standards_editor.update_rule(
            rule_id, body.heading, body.text, repo, author=user.username
        )
    except PageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no rule {rule_id}") from exc
    eng.ensure_standards_indexed(body.project_id)
    return _rule(rule)


@router.delete("/standards/rules/{rule_id:path}", status_code=204)
def delete_standards_rule(rule_id: str, request: Request, project_id: str | None = None) -> None:
    user = require_admin(request)
    eng = _engine(request)
    repo = _repo(eng, project_id)
    try:
        eng.standards_editor.delete_rule(rule_id, repo, author=user.username)
    except PageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no rule {rule_id}") from exc
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


# -- email --------------------------------------------------------------------------------------
# One sender for the whole installation: the verification and password letters go out
# from it, and so does everything written on the support page. Admin-only, and routed to
# the installation by ``store/scoped.py`` whichever account asks.


class MailSettingsView(BaseModel):
    """What the email page shows. The SMTP password is never read back -- only whether
    one is stored, and its last four characters."""

    transport: Literal["outbox", "smtp"]
    host: str = ""
    port: int = 587
    username: str = ""
    security: Literal["starttls", "ssl", "none"] = "starttls"
    from_address: str = ""
    from_name: str = "Slipwright"
    base_url: str = Field(default="", description="What the links in the letters point at.")
    support_email: str = Field(
        default="", description="Where the support page writes. Empty means the administrators."
    )
    password_set: bool = False
    password_hint: str | None = None
    configured: bool = Field(
        description="Whether letters go out over SMTP rather than to the outbox."
    )
    support_recipients: list[str] = Field(
        default_factory=list, description="Who a support request reaches as things stand."
    )


class MailSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: Literal["outbox", "smtp"] | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = Field(default=None, description="Omit to keep the stored one.")
    security: Literal["starttls", "ssl", "none"] | None = None
    from_address: str | None = None
    from_name: str | None = None
    base_url: str | None = None
    support_email: str | None = None
    clear_password: bool = False


class MailTestIn(BaseModel):
    to: str = Field(min_length=3, max_length=320)
    lang: Literal["tr", "en"] = "tr"


class MailTestResult(BaseModel):
    sent_to: str
    transport: Literal["outbox", "smtp"]


class OutboxLetter(BaseModel):
    """A letter that was never posted, for an installation whose SMTP is not set up."""

    id: str
    to_address: str
    subject: str
    body: str
    at: datetime


def _mail_view(eng: Engine) -> MailSettingsView:
    cfg = eng.mail_settings()
    password = eng.store.get_setting("mail.password")
    return MailSettingsView(
        transport=cast(Literal["outbox", "smtp"], cfg.transport),
        host=cfg.host,
        port=cfg.port,
        username=cfg.username,
        security=cast(Literal["starttls", "ssl", "none"], cfg.security),
        from_address=cfg.from_address,
        from_name=cfg.from_name,
        base_url=cfg.base_url,
        support_email=cfg.support_email,
        password_set=bool(password),
        password_hint=f"…{str(password)[-4:]}" if password else None,
        configured=cfg.configured,
        support_recipients=eng.support().recipients(),
    )


@router.get("/settings/mail", response_model=MailSettingsView)
def get_mail_settings(request: Request) -> MailSettingsView:
    """How mail leaves this installation, and where support requests land."""
    require_admin(request)
    return _mail_view(_engine(request))


@router.put("/settings/mail", response_model=MailSettingsView)
def put_mail_settings(body: MailSettingsIn, request: Request) -> MailSettingsView:
    """Change what is given; an omitted password keeps the stored one."""
    require_admin(request)
    eng = _engine(request)
    changes = body.model_dump(exclude_none=True, exclude={"clear_password"})
    if body.clear_password:
        changes["password"] = ""
    sender = (changes.get("from_address") or "").strip()
    if sender and not _EMAIL_ISH.match(sender):
        raise HTTPException(status_code=400, detail=f"not an email address: {sender}")
    # the support address may be several, separated by commas or semicolons
    for part in (changes.get("support_email") or "").replace(";", ",").split(","):
        part = part.strip()
        if part and not _EMAIL_ISH.match(part):
            raise HTTPException(status_code=400, detail=f"not an email address: {part}")
    base = (changes.get("base_url") or "").strip()
    if base and not base.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="base_url must be http(s)")
    eng.update_mail_settings(**changes)
    return _mail_view(eng)


@router.post("/settings/mail/test", response_model=MailTestResult)
def test_mail_settings(body: MailTestIn, request: Request) -> MailTestResult:
    """Post one message with the settings as they now stand, so a mistake is found here
    rather than by somebody who never got their verification link."""
    require_admin(request)
    eng = _engine(request)
    try:
        sent_to = eng.support().send_test(body.to, lang=body.lang)
    except SupportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MailTestResult(
        sent_to=sent_to,
        transport="smtp" if eng.mail_settings().configured else "outbox",
    )


@router.get("/settings/mail/outbox", response_model=list[OutboxLetter])
def get_mail_outbox(request: Request, limit: int = 20) -> list[OutboxLetter]:
    """The letters held back because no SMTP is configured. Contains live links, so it is
    admin-only like the rest of this page."""
    require_admin(request)
    return [OutboxLetter(**row) for row in read_outbox(_engine(request).store, limit=limit)]
