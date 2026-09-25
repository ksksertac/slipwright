"""HTTP surface over the engine.

Phase work never runs inside a request: endpoints persist the transition, return the
job, and hand execution to a background task. On startup the app resumes every job that
was mid-phase when the previous process died.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from slipwright.activity import (
    ActivityItem,
    AgentSummary,
    Overview,
    ProjectProgress,
    agent_summaries,
    overview,
    project_activity,
    project_progress,
)
from slipwright.board import Board, project_board
from slipwright.costs import ProjectCosts, project_costs
from slipwright.engine import (
    BriefIsRunning,
    EmptyApproval,
    Engine,
    InvalidEdit,
    JobIsRunning,
    NotAwaitingApproval,
    ProjectCloneError,
    UnknownScreen,
)
from slipwright.orchestrator import IllegalTransitionError
from slipwright.pipeline import Pipeline, pipeline
from slipwright.providers import ProviderUnavailableError
from slipwright.quota import QuotaExceeded, warn_if_unprotected
from slipwright.schemas.brief import BriefEdit, ProjectBrief
from slipwright.schemas.job import Job, JobResult, JobState, Transition
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import (
    Language,
    PlanGate,
    Project,
    ProjectPatch,
    ReviewMode,
)
from slipwright.schemas.testrun import TestRun
from slipwright.steps import StepDetail, step_detail
from slipwright.store import (
    ANY_OWNER,
    JobInProgress,
    JobNotFound,
    ProjectInUse,
    ProjectNotFound,
    TestRunNotFound,
)
from slipwright.teams import agent_for_gate, may_act_at
from slipwright.worklist import WorkList, work_list

log = logging.getLogger(__name__)


class NewJob(BaseModel):
    request: str = Field(min_length=1)
    repo_path: Path


class NewProjectJob(BaseModel):
    request: str = Field(min_length=1)


class NewProject(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    repo_path: Path | None = None
    github_repo: str | None = None
    clone_url: str | None = None
    jira_project_key: str | None = None
    profile: Profile | None = None
    review: ReviewMode = "advisory"
    language: Language = "tr"
    # which hosting service the repository lives on (Settings → Sources)
    source: str = "github"
    # a project made here reads one work list before anything is built; a project made
    # through the engine keeps the older two-gate flow unless it asks for this
    plan_gate: PlanGate = "combined"


class DeployScriptIn(BaseModel):
    path: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class DeployEdit(BaseModel):
    """The deployment proposal as a person may rewrite it at the gate (T11.6)."""

    target: Literal["aws", "azure", "none"]
    services: list[str] = Field(default_factory=list)
    scripts: list[DeployScriptIn] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    summary: str = ""


class BriefView(BaseModel):
    """The project brief plus the one thing the UI cannot work out for itself: whether
    this project is read (``analysis``) or asked about (``intake``)."""

    kind: Literal["analysis", "intake"]
    brief: ProjectBrief


class IntakeAnswers(BaseModel):
    """Answers to the round of questions on the table, by question id."""

    answers: dict[str, str] = Field(default_factory=dict)


class LocalRepo(BaseModel):
    name: str
    path: str
    is_git: bool


class LocalRepos(BaseModel):
    root: str | None
    repos: list[LocalRepo]


class AgentRouting(BaseModel):
    """Pin an agent to a provider and model for every project; both empty clears the pin."""

    provider: str | None = None
    model: str | None = None


class Version(BaseModel):
    """The build the server serves, derived from the shell it hands out."""

    build: str


class Translations(BaseModel):
    """Agent-written prose in the platform's language, keyed by what the agent wrote."""

    lang: Language
    texts: dict[str, str]


class Rejection(BaseModel):
    feedback: str = Field(min_length=1)


class ScreenVerdict(BaseModel):
    """One screen at the design gate: a yes, or a no with what should be different."""

    ok: bool
    feedback: str = ""


class DesignScreen(BaseModel):
    """A screen as the approval panel needs it: enough to name and judge it, without the
    mock itself — that is a document of its own, fetched only for the ones on screen."""

    id: str
    name: str
    platform: str = "both"
    purpose: str = ""
    approved: bool = False
    feedback: str = ""
    has_mock: bool = False
    surfaces: list[str] = Field(
        default_factory=list,
        description=(
            "The surfaces this screen was drawn for -- `web`, `mobile`, or both. Empty "
            "when the screen has a single drawing, which is what a screen on one platform "
            "and every screen drawn before surfaces existed has."
        ),
    )


class DesignReview(BaseModel):
    screens: list[DesignScreen] = Field(default_factory=list)
    principles: list[str] = Field(default_factory=list)
    waiting: bool = Field(
        default=False, description="Whether the development is stopped at this gate now."
    )


class Retry(BaseModel):
    feedback: str | None = None


class Replan(BaseModel):
    """What the person wants tried instead, when retrying the same step is pointless."""

    note: str = Field(min_length=1)


class Rerun(BaseModel):
    """Run one finished step again on the work that is already there."""

    step: Literal["test_cases", "tests", "devops"]


class Message(BaseModel):
    text: str = Field(min_length=1)


class TestCaseIn(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TestCases(BaseModel):
    test_cases: list[TestCaseIn]


class NewTestRun(BaseModel):
    job_id: str | None = Field(default=None, description="Run in this job's worktree.")


class StackEdit(BaseModel):
    """One part of the product and what it is written in (T11.5)."""

    domain: Literal["backend", "web", "mobile", "infra"]
    language: str = Field(min_length=1)
    framework: str = ""
    why: str = ""


class PlanEdit(BaseModel):
    """An edited plan: phases in the order they will run, each naming its task; the
    breakdown carries renamed tasks. Missing parts keep the current values."""

    summary: str | None = None
    stack: list[StackEdit] | None = None
    decisions: list[str] | None = None
    phases: list[dict[str, Any]]
    breakdown: dict[str, Any] | None = None


class BacklogEdit(BaseModel):
    breakdown: dict[str, Any]


class Batch(BaseModel):
    job_ids: list[str] = Field(min_length=1)


class BatchRejection(Batch):
    feedback: str = Field(min_length=1)


class BatchOutcome(BaseModel):
    job_id: str
    ok: bool
    state: str | None = None
    error: str | None = None


class BatchResult(BaseModel):
    results: list[BatchOutcome]
    approved: int


#: The surfaces of one screen, in the order the panel shows them. A screen drawn for both
#: has a document each; one drawn for a single platform has `mock` alone and no surfaces.
SURFACE_ORDER = ("web", "mobile")


def _mocks(screen: dict[str, Any]) -> dict[str, str]:
    """The drawings of one screen by surface, keeping only the ones that have a document."""
    drawn = screen.get("mocks") or {}
    if not isinstance(drawn, dict):
        return {}
    return {
        name: str(drawn.get(name) or "")
        for name in SURFACE_ORDER
        if str(drawn.get(name) or "").strip()
    }


def _surfaces(screen: dict[str, Any]) -> list[str]:
    return list(_mocks(screen))


DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
STATIC_DIR = Path(__file__).resolve().parent / "static"
BUILD_HINT = (
    "The web UI is not built. Run: cd web && npm install && npm run build\n"
    "(the JSON API is at /api, interactive docs at /docs)\n"
)


def create_app(
    engine: Engine,
    *,
    resume_on_startup: bool = True,
    require_auth: bool = True,
    dev: bool = False,
    static_dir: Path | None = None,
    jira_sweep_s: float = 3600.0,
    price_refresh_s: float = 86_400.0,
) -> FastAPI:
    """Build the app. ``require_auth=False`` (tests, trusted local use) skips login;
    ``dev=True`` allows the Vite dev server's origin (``SLIPWRIGHT_DEV=1``); ``static_dir``
    overrides where the built web UI is looked for (default: ``slipwright/api/static``)."""
    static_dir = STATIC_DIR if static_dir is None else static_dir

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine
        app.state.resume_thread = None
        # a server anybody can sign up to, with nothing limiting what one account takes,
        # is a machine waiting to fall over. Said once, loudly, and not enforced: refusing
        # to start would be worse than the risk it is warning about.
        unprotected = warn_if_unprotected(
            engine.quotas.limits(), open_to_strangers=require_auth
        )
        if unprotected:
            log.warning("%s", unprotected)
        if resume_on_startup:
            threading.Thread(target=engine.ensure_standards_indexed, daemon=True).start()
        if resume_on_startup:
            thread = threading.Thread(target=_resume_all, args=(engine,), daemon=True)
            thread.start()
            app.state.resume_thread = thread
        stop = threading.Event()
        app.state.sweep_stop = stop
        if resume_on_startup and jira_sweep_s > 0:
            threading.Thread(
                target=_jira_sweeper, args=(engine, jira_sweep_s, stop), daemon=True
            ).start()
        if resume_on_startup and price_refresh_s > 0:
            threading.Thread(
                target=_price_refresher, args=(engine, price_refresh_s, stop), daemon=True
            ).start()
        yield
        stop.set()

    from slipwright.api.auth import (
        auth_dependency,
        require_admin,
        require_owner,
        require_verified,
    )
    from slipwright.api.auth import router as auth_router
    from slipwright.api.settings import router as settings_router
    from slipwright.api.support import router as support_router
    from slipwright.api.teams import router as teams_router

    app = FastAPI(
        title="Slipwright",
        lifespan=lifespan,
        dependencies=[Depends(auth_dependency(enabled=require_auth))],
    )
    default_openapi = app.openapi

    def tightened_openapi() -> dict[str, Any]:
        return _tighten_response_schemas(default_openapi())

    app.openapi = tightened_openapi  # type: ignore[method-assign]
    if dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=DEV_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def name_the_build(request: Request, call_next: Any) -> Any:
        """Every response says which build answered it, so an editor or a script can
        tell when the server moved under it."""
        response = await call_next(request)
        response.headers["X-Slipwright-Version"] = _build_id(static_dir)
        return response

    api = APIRouter()
    app.include_router(auth_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(support_router, prefix="/api")
    app.include_router(teams_router, prefix="/api")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/version", response_model=Version)
    def get_version() -> Version:
        """Which build this server serves. The page compares it with its own and says
        when a browser is still running an older one — a hashed bundle it cached."""
        return Version(build=_build_id(static_dir))

    def _engine(request: Request) -> Engine:
        eng: Engine = request.app.state.engine
        return eng

    def _owner(request: Request) -> str | None:
        """Whose data this request may touch.

        ``ANY_OWNER`` when there is nobody to separate: authentication is off (the test
        suite, a trusted local run) and the caller is the synthetic admin. Otherwise the
        account the person works on -- their own, or, for somebody invited onto one of its
        agents, the account that invited them. A row belonging to anybody else is simply
        not found.
        """
        user = getattr(request.state, "user", None)
        if user is None or user.id == "anonymous":
            return ANY_OWNER
        return str(user.tenant_id)

    def _my_agents(request: Request) -> set[RoleName]:
        """The agents the caller acts as. Empty for an owner, who acts as all of them."""
        user = getattr(request.state, "user", None)
        if user is None or not user.is_member:
            return set()
        agents: set[RoleName] = _engine(request).raw_store.agents_of(user.id)
        return agents

    def _may_act(request: Request, job: Job) -> None:
        """Guard the gate: approving, rejecting and editing what is being approved.

        The owner may act at every gate of their own developments. A member may act only
        where their own agent is waiting -- the Architect at the architecture gate, QA at
        the test gates -- and nowhere at all on a development that is not waiting, because
        what moves a stopped one (retry, replan, re-run) is the owner's to do.

        Nobody acts on the worked example. It is a finished development written as data,
        with no checkout behind it, so anything that would run something in it can only
        fail further in; it is there to be read and then deleted.
        """
        _refuse_if_demo(request, job)
        user = getattr(request.state, "user", None)
        if user is None or not user.is_member:
            return
        if may_act_at(user, job, _my_agents(request)):
            return
        agent = agent_for_gate(job.state)
        raise HTTPException(
            status_code=403,
            detail=(
                f"this gate belongs to the {agent.value} agent"
                if agent is not None
                else "this development is not waiting for one of your agents"
            ),
        )

    def _may_configure(request: Request, role: RoleName) -> None:
        """Agent setup: the owner's administrator, or whoever holds that one agent."""
        if role in _my_agents(request):
            return
        require_admin(request)

    def _agents(eng: Engine, request: Request) -> list[AgentSummary]:
        owner = _owner(request)
        people: dict[RoleName, int] = {}
        holders: dict[RoleName, list[str]] = {}
        if owner is not None and owner != ANY_OWNER:
            for m in eng.raw_store.list_members(owner):
                if m.open:
                    people[m.role] = people.get(m.role, 0) + 1
                    holders.setdefault(m.role, []).append(m.name or m.email)
        return agent_summaries(
            eng.store.list(owner_id=owner),
            eng.seed_profile,
            route=eng.effective_routing,
            assigned=eng.agent_routing,
            people=people,
            mine=_my_agents(request),
            holders=holders,
        )

    def _get(eng: Engine, job_id: str, request: Request) -> Job:
        try:
            return eng.store.get(job_id, _owner(request))
        except JobNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _refuse_if_demo(request: Request, job: Job) -> None:
        """Refuse anything that would run the worked example."""
        if job.project_id is None:
            return
        try:
            project = _engine(request).store.get_project(job.project_id, _owner(request))
        except ProjectNotFound:
            return
        if project.is_demo:
            raise HTTPException(
                status_code=409,
                detail="this is the example project: it is there to read, not to run",
            )

    def _get_project(eng: Engine, project_id: str, request: Request) -> Project:
        try:
            return eng.store.get_project(project_id, _owner(request))
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _start(eng: Engine, job: Job, background: BackgroundTasks) -> Job:
        # refused here rather than at creation: this is where it would take a thread, a
        # worktree and a container, which is what there is a limited number of
        try:
            eng.quotas.check_new_job(job.owner_id)
        except QuotaExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        job = eng.start(job.id, run=False)
        background.add_task(_resume, eng, job.id)
        return job

    # -- dashboard -----------------------------------------------------------------------

    @api.get("/overview", response_model=Overview)
    def get_overview(request: Request, recent: int = 20) -> Overview:
        """Numbers, pending approvals and recent activity across every project."""
        eng = _engine(request)
        owner = _owner(request)
        return overview(
            len(eng.store.list_projects(owner)), eng.store.list(owner_id=owner), recent=recent
        )

    @api.get("/activity", response_model=list[ActivityItem])
    def get_all_activity(
        request: Request, limit: int | None = 50, role: RoleName | None = None
    ) -> list[ActivityItem]:
        jobs = _engine(request).store.list(owner_id=_owner(request))
        return project_activity(jobs, limit=limit, role=role)

    @api.get("/agents", response_model=list[AgentSummary])
    def get_agents(request: Request) -> list[AgentSummary]:
        """The agent cards: scope, default model routing and how much each has worked."""
        eng = _engine(request)
        return _agents(eng, request)

    @api.put("/agents/{role}/routing", response_model=AgentSummary)
    def put_agent_routing(role: RoleName, body: AgentRouting, request: Request) -> AgentSummary:
        """Pin an agent to a provider and model. 400 when the provider is unknown, has no
        key, or no model was named -- the job would only fail at its first call."""
        _may_configure(request, role)
        eng = _engine(request)
        try:
            eng.assign_agent(role, body.provider, body.model)
        except (ValueError, ProviderUnavailableError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return next(a for a in _agents(eng, request) if a.role is role)

    # -- projects ------------------------------------------------------------------------

    @api.get("/local-repos", response_model=LocalRepos)
    def local_repos(request: Request) -> LocalRepos:
        """Folders the server can register as local checkouts (the mounted repos root)."""
        eng = _engine(request)
        root = eng.local_repos_root
        return LocalRepos(
            root=root.as_posix() if root else None,
            repos=[LocalRepo(**r) for r in eng.local_repos()],
        )

    @api.post("/projects", response_model=Project, status_code=201)
    def create_project(body: NewProject, request: Request) -> Project:
        require_owner(request)
        require_verified(request)
        eng = _engine(request)
        if body.repo_path is not None and not body.repo_path.is_dir():
            raise HTTPException(
                status_code=400, detail=f"repo_path is not a directory: {body.repo_path}"
            )
        if body.repo_path is None and body.github_repo is None and body.clone_url is None:
            raise HTTPException(
                status_code=400, detail="give a repo_path, a github_repo or a clone_url"
            )
        owner = _owner(request)
        try:
            eng.quotas.check_new_project(None if owner == ANY_OWNER else owner)
        except QuotaExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        try:
            return eng.create_project(
                Project(
                    **body.model_dump(),
                    # ANY_OWNER is the sentinel for "nobody to separate"; a project made
                    # then belongs to the installation, not to an account called "*"
                    owner_id=None if owner == ANY_OWNER else owner,
                )
            )
        except ProjectCloneError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.get("/projects", response_model=list[Project])
    def list_projects(request: Request) -> list[Project]:
        return _engine(request).store.list_projects(_owner(request))

    @api.get("/projects/{project_id}", response_model=Project)
    def get_project(project_id: str, request: Request) -> Project:
        return _get_project(_engine(request), project_id, request)

    @api.patch("/projects/{project_id}", response_model=Project)
    def patch_project(project_id: str, body: ProjectPatch, request: Request) -> Project:
        require_owner(request)
        eng = _engine(request)
        project = _get_project(eng, project_id, request)
        changes = body.model_dump(exclude_unset=True)
        try:
            # merge as plain data so nested models (profile, supervisor) validate cleanly
            updated = Project.model_validate({**project.model_dump(), **changes})
            # through the engine: naming a GitHub repository here wires the checkout's remote
            return eng.update_project(updated)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.delete("/projects/{project_id}", status_code=204)
    def delete_project(project_id: str, request: Request) -> None:
        require_owner(request)
        eng = _engine(request)
        _get_project(eng, project_id, request)
        try:
            eng.store.delete_project(project_id)
        except ProjectInUse as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @api.post("/projects/{project_id}/jobs", response_model=Job, status_code=201)
    def create_project_job(
        project_id: str, body: NewProjectJob, request: Request, background: BackgroundTasks
    ) -> Job:
        require_owner(request)
        require_verified(request)
        eng = _engine(request)
        _get_project(eng, project_id, request)
        return _start(eng, eng.create_job(body.request, project_id=project_id), background)

    @api.get("/projects/{project_id}/jobs", response_model=list[Job])
    def list_project_jobs(project_id: str, request: Request) -> list[Job]:
        eng = _engine(request)
        _get_project(eng, project_id, request)
        return eng.store.list(project_id, owner_id=_owner(request))

    @api.get("/projects/{project_id}/board", response_model=Board)
    def get_board(project_id: str, request: Request) -> Board:
        """Epics, stories and tasks of every job whose plan was approved, with statuses."""
        eng = _engine(request)
        _get_project(eng, project_id, request)
        return project_board(project_id, eng.store.list(project_id, owner_id=_owner(request)))

    @api.get("/projects/{project_id}/pipeline", response_model=Pipeline)
    def get_pipeline(project_id: str, request: Request) -> Pipeline:
        """Every development as a lane of step cards, newest first."""
        eng = _engine(request)
        _get_project(eng, project_id, request)
        jobs = sorted(
            eng.store.list(project_id, owner_id=_owner(request)),
            key=lambda j: j.created_at,
            reverse=True,
        )
        return pipeline(jobs, project_id=project_id)

    @api.get("/projects/{project_id}/progress", response_model=ProjectProgress)
    def get_progress(project_id: str, request: Request) -> ProjectProgress:
        eng = _engine(request)
        _get_project(eng, project_id, request)
        return project_progress(project_id, eng.store.list(project_id, owner_id=_owner(request)))

    @api.get("/projects/{project_id}/costs", response_model=ProjectCosts)
    def get_costs(project_id: str, request: Request) -> ProjectCosts:
        """What this project's developments cost, what they were expected to cost, and
        the gap. Spend is read from the per-call log; the expectation is arithmetic over
        what the roles have actually used here, so it sharpens as the project is used."""
        eng = _engine(request)
        project = _get_project(eng, project_id, request)
        owner = _owner(request)
        jobs = sorted(
            eng.store.list(project_id, owner_id=owner), key=lambda j: j.created_at, reverse=True
        )
        return project_costs(
            project_id,
            jobs,
            profile=eng.project_profile(project),
            stored_prices=eng.store.list_prices(),
            history=eng.store.list(owner_id=owner),  # every job of this account teaches the average
            route=eng.effective_routing,  # the model that will answer, not the one named
        )

    @api.get("/projects/{project_id}/activity", response_model=list[ActivityItem])
    def get_activity(
        project_id: str, request: Request, limit: int | None = None
    ) -> list[ActivityItem]:
        """Every job's history, newest first; ``index`` addresses the detail endpoint."""
        eng = _engine(request)
        _get_project(eng, project_id, request)
        return project_activity(eng.store.list(project_id, owner_id=_owner(request)), limit=limit)

    @api.get("/projects/{project_id}/translations", response_model=Translations)
    def get_translations(project_id: str, request: Request, lang: Language) -> Translations:
        """What this project's agents wrote, in ``lang``.

        The agents write in the project's language; the page is read in the platform's.
        When they differ this is the bridge -- keyed by the source text, so the page looks
        up whatever string it is about to render and falls back to it when there is no
        entry yet. A development already written in ``lang`` contributes nothing."""
        eng = _engine(request)
        _get_project(eng, project_id, request)
        return Translations(lang=lang, texts=eng.translations(lang, project_id=project_id))

    @api.get("/translations", response_model=Translations)
    def get_all_translations(request: Request, lang: Language) -> Translations:
        """The same bridge across every project, for the dashboard's feed."""
        return Translations(
            lang=lang, texts=_engine(request).translations(lang, owner_id=_owner(request))
        )

    # -- test runs -----------------------------------------------------------------------

    # -- project brief: what the agents are told the project is (T11.1-T11.3) ------------

    def _brief_view(eng: Engine, project_id: str, request: Request) -> BriefView:
        project = _get_project(eng, project_id, request)
        kind = cast(Literal["analysis", "intake"], eng.brief_kind(project))
        return BriefView(kind=kind, brief=eng.store.get_brief(project_id))

    @api.get("/projects/{project_id}/brief", response_model=BriefView)
    def get_brief(project_id: str, request: Request) -> BriefView:
        """What Slipwright knows about the project, and how it came to know it."""
        return _brief_view(_engine(request), project_id, request)

    @api.post("/projects/{project_id}/brief/analysis", response_model=BriefView, status_code=202)
    def start_analysis(project_id: str, request: Request, background: BackgroundTasks) -> BriefView:
        """Read the checkout and propose the brief; the answer comes back on the brief."""
        require_owner(request)
        require_verified(request)
        eng = _engine(request)
        _get_project(eng, project_id, request)
        try:
            eng.start_analysis(project_id)
        except BriefIsRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        background.add_task(_execute_analysis, eng, project_id)
        return _brief_view(eng, project_id, request)

    @api.post("/projects/{project_id}/brief/intake", response_model=BriefView, status_code=202)
    def start_intake(
        project_id: str, body: IntakeAnswers, request: Request, background: BackgroundTasks
    ) -> BriefView:
        """Answer the questions on the table (if any) and ask for the next round."""
        require_owner(request)
        require_verified(request)
        eng = _engine(request)
        _get_project(eng, project_id, request)
        try:
            eng.start_intake(project_id, body.answers)
        except BriefIsRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        background.add_task(_execute_intake, eng, project_id)
        return _brief_view(eng, project_id, request)

    @api.put("/projects/{project_id}/brief", response_model=BriefView)
    def save_brief(project_id: str, body: BriefEdit, request: Request) -> BriefView:
        require_owner(request)
        """Take the person's edits; approving is what lets the agents read any of it."""
        eng = _engine(request)
        _get_project(eng, project_id, request)
        try:
            eng.save_brief(project_id, body)
        except BriefIsRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (EmptyApproval, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _brief_view(eng, project_id, request)

    @api.post("/projects/{project_id}/test-runs", response_model=TestRun, status_code=202)
    def start_test_run(
        project_id: str, body: NewTestRun, request: Request, background: BackgroundTasks
    ) -> TestRun:
        """Run the profile's test command on the main checkout, or in a job's worktree."""
        require_owner(request)
        require_verified(request)
        eng = _engine(request)
        _get_project(eng, project_id, request)
        if body.job_id is not None:
            _get(eng, body.job_id, request)
        try:
            run = eng.start_test_run(project_id, body.job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not run.terminal:
            background.add_task(_execute_test_run, eng, run.id)
        return run

    @api.get("/projects/{project_id}/test-runs", response_model=list[TestRun])
    def list_test_runs(
        project_id: str, request: Request, job_id: str | None = None
    ) -> list[TestRun]:
        eng = _engine(request)
        _get_project(eng, project_id, request)
        return eng.store.list_test_runs(project_id, job_id, owner_id=_owner(request))

    def _get_run(eng: Engine, run_id: str, request: Request) -> TestRun:
        try:
            return eng.store.get_test_run(run_id, _owner(request))
        except TestRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @api.get("/test-runs/{run_id}", response_model=TestRun)
    def get_test_run(run_id: str, request: Request) -> TestRun:
        return _get_run(_engine(request), run_id, request)

    @api.get("/test-runs/{run_id}/output", response_class=PlainTextResponse)
    def get_test_run_output(run_id: str, request: Request) -> str:
        eng = _engine(request)
        return eng.test_run_output(_get_run(eng, run_id, request))

    # -- jobs ----------------------------------------------------------------------------

    @api.post("/jobs", response_model=Job, status_code=201)
    def create_job(body: NewJob, request: Request, background: BackgroundTasks) -> Job:
        """Start a job straight from a repository path (its project is found or created)."""
        require_owner(request)
        require_verified(request)
        eng = _engine(request)
        if not body.repo_path.is_dir():
            raise HTTPException(
                status_code=400, detail=f"repo_path is not a directory: {body.repo_path}"
            )
        return _start(eng, eng.create_job(body.request, body.repo_path), background)

    @api.get("/jobs", response_model=list[Job])
    def list_jobs(request: Request) -> list[Job]:
        return _engine(request).store.list(owner_id=_owner(request))

    @api.get("/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str, request: Request) -> Job:
        return _get(_engine(request), job_id, request)

    @api.delete("/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str, request: Request) -> None:
        require_owner(request)
        """Delete a finished job (worktree, branch, port and rows). Running jobs: 409."""
        eng = _engine(request)
        # deleting it is not running it: the example is meant to be thrown away
        _get(eng, job_id, request)
        try:
            eng.delete_job(job_id)
        except JobInProgress as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @api.get("/jobs/{job_id}/history/{index}", response_model=Transition)
    def get_transition(job_id: str, index: int, request: Request) -> Transition:
        """One history entry in full (its ``detail`` holds the diff, log or JSON)."""
        job = _get(_engine(request), job_id, request)
        if index < 0 or index >= len(job.history):
            raise HTTPException(status_code=404, detail=f"no history entry {index}")
        return job.history[index]

    @api.get("/jobs/{job_id}/steps/{step_key}", response_model=StepDetail)
    def get_step_detail(job_id: str, step_key: str, request: Request) -> StepDetail:
        """What one pipeline step produced: the backlog it wrote, the decisions it took,
        the files it touched, the cases it proposed — each with when, and with whether it
        reached Jira. ``step_key`` is the key the lane card carries."""
        job = _get(_engine(request), job_id, request)
        detail = step_detail(job, step_key)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no step {step_key!r} on this job")
        return detail

    @api.post("/jobs/approve", response_model=BatchResult)
    def approve_many(body: Batch, request: Request, background: BackgroundTasks) -> BatchResult:
        """Approve several gates at once. Each job is an ordinary approval recorded on
        that job; one that is not at a gate is reported, never the whole batch."""
        eng = _engine(request)
        results: list[BatchOutcome] = []
        for job_id in dict.fromkeys(body.job_ids):
            try:
                _may_act(request, _get(eng, job_id, request))
                job = eng.approve(job_id, run=False)
            except HTTPException as exc:
                results.append(BatchOutcome(job_id=job_id, ok=False, error=str(exc.detail)))
                continue
            except (NotAwaitingApproval, EmptyApproval) as exc:
                results.append(BatchOutcome(job_id=job_id, ok=False, error=str(exc)))
                continue
            background.add_task(_resume, eng, job.id)
            results.append(BatchOutcome(job_id=job_id, ok=True, state=job.state.value))
        return BatchResult(results=results, approved=sum(1 for r in results if r.ok))

    @api.post("/jobs/reject", response_model=BatchResult)
    def reject_many(
        body: BatchRejection, request: Request, background: BackgroundTasks
    ) -> BatchResult:
        """Reject several gates with one feedback text."""
        eng = _engine(request)
        results: list[BatchOutcome] = []
        for job_id in dict.fromkeys(body.job_ids):
            try:
                _may_act(request, _get(eng, job_id, request))
                job = eng.reject(job_id, body.feedback, run=False)
            except HTTPException as exc:
                results.append(BatchOutcome(job_id=job_id, ok=False, error=str(exc.detail)))
                continue
            except NotAwaitingApproval as exc:
                results.append(BatchOutcome(job_id=job_id, ok=False, error=str(exc)))
                continue
            background.add_task(_resume, eng, job.id)
            results.append(BatchOutcome(job_id=job_id, ok=True, state=job.state.value))
        return BatchResult(results=results, approved=sum(1 for r in results if r.ok))

    @api.post("/jobs/{job_id}/approve", response_model=Job)
    def approve(job_id: str, request: Request, background: BackgroundTasks) -> Job:
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        try:
            job = eng.approve(job_id, run=False)
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EmptyApproval as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        background.add_task(_resume, eng, job.id)
        return job

    @api.post("/jobs/{job_id}/reject", response_model=Job)
    def reject(job_id: str, body: Rejection, request: Request, background: BackgroundTasks) -> Job:
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        try:
            job = eng.reject(job_id, body.feedback, run=False)
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        background.add_task(_resume, eng, job.id)
        return job

    @api.get("/jobs/{job_id}/design", response_model=DesignReview)
    def design_review(job_id: str, request: Request) -> DesignReview:
        """The screens of this development, with where each one stands."""
        job = _get(_engine(request), job_id, request)
        design = job.data.design or {}
        approvals = job.data.design_approvals or {}
        feedback = job.data.design_feedback or {}
        return DesignReview(
            waiting=job.state is JobState.AWAITING_DESIGN_APPROVAL,
            principles=[str(p) for p in design.get("principles") or []],
            screens=[
                DesignScreen(
                    id=str(s.get("id") or ""),
                    name=str(s.get("name") or ""),
                    platform=str(s.get("platform") or "both"),
                    purpose=str(s.get("purpose") or ""),
                    approved=bool(approvals.get(str(s.get("id")))),
                    feedback=str(feedback.get(str(s.get("id")) or "") or ""),
                    has_mock=bool(str(s.get("mock") or "").strip()) or bool(_surfaces(s)),
                    surfaces=_surfaces(s),
                )
                for s in design.get("screens") or []
            ],
        )

    @api.get("/jobs/{job_id}/design/{screen_id}/mock", response_class=HTMLResponse)
    def design_mock(
        job_id: str, screen_id: str, request: Request, surface: str | None = None
    ) -> HTMLResponse:
        """One screen's mock, as its own document so an iframe can draw it.

        A screen drawn for both surfaces has one document each; ``surface`` picks which,
        and anything else -- a screen on one platform, a screen drawn before surfaces
        existed -- answers with its single drawing however it is asked for.

        The document is written by a model, so it is served locked down and framed with no
        same-origin access: the headers below forbid every script, every network request
        and every external asset, which leaves exactly what a mock is -- markup, inline
        styles and inline images.
        """
        job = _get(_engine(request), job_id, request)
        screens = (job.data.design or {}).get("screens") or []
        screen = next((s for s in screens if str(s.get("id")) == screen_id), None)
        if screen is None:
            raise HTTPException(status_code=404, detail=f"no screen {screen_id}")
        drawn = _mocks(screen)
        body = drawn.get(surface or "") or str(screen.get("mock") or "")
        if not body and drawn:
            body = next(iter(drawn.values()))
        return HTMLResponse(
            content=body,
            headers={
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "img-src data:; font-src data:; sandbox"
                ),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @api.post("/jobs/{job_id}/design/{screen_id}", response_model=Job)
    def review_screen(
        job_id: str,
        screen_id: str,
        body: ScreenVerdict,
        request: Request,
        background: BackgroundTasks,
    ) -> Job:
        """Sign off one screen, or send it back with what should be different."""
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        try:
            job = eng.review_screen(
                job_id, screen_id, ok=body.ok, feedback=body.feedback, run=False
            )
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except UnknownScreen as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except EmptyApproval as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        background.add_task(_resume, eng, job.id)
        return job

    @api.put("/jobs/{job_id}/profile", response_model=Job)
    def set_profile(job_id: str, body: Profile, request: Request) -> Job:
        """Edit the proposed profile while the job awaits its approval."""
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        try:
            return eng.set_profile(job_id, body)
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @api.put("/jobs/{job_id}/backlog", response_model=Job)
    def set_backlog(job_id: str, body: BacklogEdit, request: Request) -> Job:
        """Edit the proposed backlog while the job awaits its approval."""
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        try:
            return eng.set_backlog(job_id, body.breakdown)
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidEdit as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.put("/jobs/{job_id}/plan", response_model=Job)
    def set_plan(job_id: str, body: PlanEdit, request: Request) -> Job:
        """Edit the proposed plan while the job awaits the architecture approval; the
        edit must pass the Architect's own checks (one phase per task)."""
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        try:
            return eng.set_plan(job_id, body.model_dump(exclude_none=True))
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidEdit as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.put("/jobs/{job_id}/tests", response_model=Job)
    def set_tests(job_id: str, body: TestCases, request: Request) -> Job:
        """Edit the proposed test list while the job awaits its approval."""
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        try:
            return eng.set_test_cases(job_id, [c.model_dump() for c in body.test_cases])
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @api.put("/jobs/{job_id}/deploy", response_model=Job)
    def set_deploy(job_id: str, body: DeployEdit, request: Request) -> Job:
        """Edit the deployment proposal while the job waits at the deployment gate."""
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        try:
            return eng.set_deploy(job_id, body.model_dump(exclude_unset=True))
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidEdit as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.get("/jobs/{job_id}/worklist", response_model=WorkList)
    def get_worklist(job_id: str, request: Request) -> WorkList:
        """What each agent is about to do, grouped by agent: the list the person reads
        before starting a development, and the one they edit at the plan gate."""
        eng = _engine(request)
        return work_list(_get(eng, job_id, request))

    @api.get("/jobs/{job_id}/result", response_model=JobResult)
    def get_job_result(job_id: str, request: Request) -> JobResult:
        """What the development produced: branch, commits, files and how to get them."""
        eng = _engine(request)
        _get(eng, job_id, request)  # 404 for an unknown job
        result: JobResult = eng.job_result(job_id)
        return result

    @api.post("/jobs/{job_id}/retry", response_model=Job)
    def retry(
        job_id: str, request: Request, background: BackgroundTasks, body: Retry | None = None
    ) -> Job:
        """Continue a failed job from the step it failed in."""
        require_owner(request)
        eng = _engine(request)
        _refuse_if_demo(request, _get(eng, job_id, request))
        try:
            job = eng.retry(job_id, run=False, feedback=(body.feedback if body else None))
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail="only a failed job can be retried") from exc
        background.add_task(_resume, eng, job.id)
        return job

    @api.post("/jobs/{job_id}/replan", response_model=Job)
    def replan(job_id: str, body: Replan, request: Request, background: BackgroundTasks) -> Job:
        """Send a failed job back to the plan with what should be tried instead."""
        require_owner(request)
        eng = _engine(request)
        _refuse_if_demo(request, _get(eng, job_id, request))
        try:
            job = eng.replan(job_id, body.note, run=False)
        except NotAwaitingApproval as exc:
            raise HTTPException(
                status_code=409, detail="only a failed development can be planned again"
            ) from exc
        except EmptyApproval as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        background.add_task(_resume, eng, job.id)
        return job

    @api.post("/jobs/{job_id}/rerun", response_model=Job)
    def rerun(job_id: str, body: Rerun, request: Request, background: BackgroundTasks) -> Job:
        """Run the tests, or the DevOps step, again on a development that has stopped."""
        require_owner(request)
        eng = _engine(request)
        _refuse_if_demo(request, _get(eng, job_id, request))
        try:
            job = eng.rerun(job_id, body.step, run=False)
        except JobIsRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # IllegalTransitionError is a ValueError, so it has to be caught first
        except IllegalTransitionError as exc:
            raise HTTPException(
                status_code=409, detail=f"this development cannot re-run {body.step}: {exc}"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        background.add_task(_resume, eng, job.id)
        return job

    @api.post("/jobs/{job_id}/undo", response_model=Job)
    def undo(job_id: str, body: Rejection, request: Request) -> Job:
        """Overrule the supervisor's automatic approval: the feedback reaches the next role
        through the inbox and the approval is marked undone."""
        require_owner(request)
        eng = _engine(request)
        _refuse_if_demo(request, _get(eng, job_id, request))
        try:
            return eng.undo_auto_approval(job_id, body.feedback)
        except NotAwaitingApproval as exc:
            raise HTTPException(
                status_code=409, detail="nothing the supervisor approved is left to undo"
            ) from exc

    @api.post("/jobs/{job_id}/message", response_model=Job)
    def message(job_id: str, body: Message, request: Request) -> Job:
        require_owner(request)
        eng = _engine(request)
        _may_act(request, _get(eng, job_id, request))
        return eng.message(job_id, body.text)

    # -- live events ---------------------------------------------------------------------

    @api.get("/events", include_in_schema=True)
    async def events(
        request: Request,
        project_id: str | None = None,
        limit: int | None = None,
        keepalive_s: float = 15.0,
        since: int | None = None,
    ) -> StreamingResponse:
        """Server-sent events: ``job.state``, ``job.data``, ``test_run.state``,
        ``activity`` and ``project``. ``project_id`` filters; ``limit`` closes the
        stream after that many events (for scripts and tests). ``since`` (or the
        ``Last-Event-ID`` header a reader sends when it reconnects) replays what it
        missed, as far back as the bus still holds."""
        eng = _engine(request)
        owner = _owner(request)
        return StreamingResponse(
            _event_stream(
                eng,
                # the bus filters on this; `project_id` below is only the reader's own
                # convenience and is not, and never was, an authorisation check
                owner_id=None if owner == ANY_OWNER else owner,
                project_id=project_id,
                limit=limit,
                keepalive_s=keepalive_s,
                since=since if since is not None else _last_event_id(request),
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(api, prefix="/api")
    _mount_spa(app, static_dir)
    return app


def _build_id(static_dir: Path) -> str:
    """A short digest of the built shell: it names the hashed bundles, so it changes on
    every deploy and not otherwise. "dev" when there is no build."""
    index = static_dir / "index.html"
    try:
        digest: str = hashlib.sha256(index.read_bytes()).hexdigest()
        return digest[:12]
    except OSError:
        return "dev"


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built React app with an SPA fallback, or a build hint without one.

    Registered last so ``/api`` routes win; unknown ``/api`` paths stay 404 instead of
    falling back to the shell."""
    index = static_dir / "index.html"
    if not index.is_file():

        @app.get("/", include_in_schema=False)
        def build_hint() -> PlainTextResponse:
            return PlainTextResponse(BUILD_HINT, status_code=503)

        return

    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404)
        candidate = static_dir / path
        if path and candidate.is_file() and static_dir in candidate.resolve().parents:
            return FileResponse(candidate)
        # the shell names hashed bundles: a browser that keeps an old copy after a redeploy
        # asks for bundles that no longer exist and shows nothing, so it must revalidate
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def openapi_schema() -> dict[str, Any]:
    """The API description, independent of any engine (for ``schemas/openapi.json``)."""
    app = create_app(cast(Engine, None), resume_on_startup=False, require_auth=False)
    return app.openapi()


def _tighten_response_schemas(schema: dict[str, Any]) -> dict[str, Any]:
    """Mark every property of a response-only model as required.

    Pydantic leaves fields with defaults optional even in serialization mode, which
    would make ``job.id`` nullable in the generated TypeScript client. Models that also
    appear in a request body keep their optional fields.
    """
    components: dict[str, Any] = schema.get("components", {}).get("schemas", {})

    def refs(node: Any, out: set[str]) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                out.add(ref.rsplit("/", 1)[1])
            for value in node.values():
                refs(value, out)
        elif isinstance(node, list):
            for value in node:
                refs(value, out)

    inputs: set[str] = set()
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "requestBody" in operation:
                refs(operation["requestBody"], inputs)
    # anything reachable from an input model is an input model too
    frontier = list(inputs)
    while frontier:
        name = frontier.pop()
        nested: set[str] = set()
        refs(components.get(name, {}), nested)
        for n in nested - inputs:
            inputs.add(n)
            frontier.append(n)

    for name, model in components.items():
        if name in inputs or "properties" not in model:
            continue
        model["required"] = sorted(model["properties"])
    return schema


def _last_event_id(request: Request) -> int | None:
    """A reader reconnecting sends the last id it saw; honour it as ``since``."""
    raw = request.headers.get("last-event-id")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


async def _event_stream(
    engine: Engine,
    *,
    owner_id: str | None,
    project_id: str | None,
    limit: int | None,
    keepalive_s: float,
    since: int | None = None,
) -> AsyncIterator[str]:
    import anyio

    sent = 0
    # the owner filter is applied by the bus, on publish and on replay; `project_id` below
    # narrows what this reader asked for and decides nothing about what it may see
    with engine.events.subscribe(owner_id) as q:
        yield ": connected\n\n"
        if since is not None:
            # what was published while this reader was away, oldest first
            for event_id, missed in engine.events.since(since, owner_id):
                if project_id is not None and missed.project_id != project_id:
                    continue
                yield missed.sse(event_id)
                sent += 1
                if limit is not None and sent >= limit:
                    return
        while limit is None or sent < limit:
            try:
                event = await anyio.to_thread.run_sync(q.get, True, keepalive_s)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if project_id is not None and event.project_id != project_id:
                continue
            sent += 1
            yield event.sse(sent)


def _resume(engine: Engine, job_id: str) -> None:
    try:
        engine.resume(job_id)
    except Exception:  # noqa: BLE001 - a background thread has nobody to raise to
        log.exception("job %s: background run failed", job_id)


def _execute_test_run(engine: Engine, run_id: str) -> None:
    try:
        engine.execute_test_run(run_id)
    except Exception:  # noqa: BLE001 - a background thread has nobody to raise to
        log.exception("test run %s: background run failed", run_id)


def _execute_analysis(engine: Engine, project_id: str) -> None:
    try:
        engine.execute_analysis(project_id)
    except Exception:  # noqa: BLE001 - a background thread has nobody to raise to
        log.exception("project %s: analysis failed", project_id)


def _execute_intake(engine: Engine, project_id: str) -> None:
    try:
        engine.execute_intake(project_id)
    except Exception:  # noqa: BLE001 - a background thread has nobody to raise to
        log.exception("project %s: intake round failed", project_id)


def _jira_sweeper(engine: Engine, every_s: float, stop: threading.Event) -> None:
    """The PO's round: once after startup (after the jobs resumed), then every hour."""
    stop.wait(5.0)  # let the resumed jobs take their locks first
    while not stop.is_set():
        try:
            engine.jira_sweep()
        except Exception:  # noqa: BLE001 - a sweep must never kill the timer
            log.exception("jira sweep failed")
        stop.wait(every_s)


def _price_refresher(engine: Engine, every_s: float, stop: threading.Event) -> None:
    """Once shortly after startup, then daily. No vendor has a pricing API, so this reads
    the published table; a failure leaves the stored prices alone and tries again."""
    stop.wait(10.0)
    while not stop.is_set():
        try:
            engine.refresh_prices()
        except Exception:  # noqa: BLE001 - a fetch must never kill the timer
            log.exception("price refresh failed")
        stop.wait(every_s)


def _resume_all(engine: Engine) -> None:
    """Resume every persisted job, each in its own thread so in-flight jobs overlap.

    Deliberately unscoped: this is the server starting, not somebody asking. Work that
    was in flight when the last process died belongs to whoever owns it and must carry
    on, so it is listed across every account -- and each job then runs on its own
    owner's credentials.
    """
    threads = [
        threading.Thread(target=_resume, args=(engine, job.id), daemon=True)
        for job in engine.store.list()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


__all__ = [
    "Message",
    "NewJob",
    "NewProject",
    "NewProjectJob",
    "Rejection",
    "TestCaseIn",
    "TestCases",
    "create_app",
    "openapi_schema",
]
