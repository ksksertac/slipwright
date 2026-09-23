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
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
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
from slipwright.engine import (
    EmptyApproval,
    Engine,
    InvalidEdit,
    JobIsRunning,
    NotAwaitingApproval,
    ProjectCloneError,
)
from slipwright.orchestrator import IllegalTransitionError
from slipwright.pipeline import Pipeline, pipeline
from slipwright.providers import ProviderUnavailableError
from slipwright.schemas.job import Job, JobResult, Transition
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import (
    Language,
    PlanGate,
    Project,
    ProjectPatch,
    ReviewMode,
)
from slipwright.schemas.testrun import TestRun
from slipwright.store import (
    JobInProgress,
    JobNotFound,
    ProjectInUse,
    ProjectNotFound,
    TestRunNotFound,
)
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
    # a project made here reads one work list before anything is built; a project made
    # through the engine keeps the older two-gate flow unless it asks for this
    plan_gate: PlanGate = "combined"


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


class Rejection(BaseModel):
    feedback: str = Field(min_length=1)


class Retry(BaseModel):
    feedback: str | None = None


class Rerun(BaseModel):
    """Run one finished step again on the work that is already there."""

    step: Literal["tests", "devops"]


class Message(BaseModel):
    text: str = Field(min_length=1)


class TestCaseIn(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TestCases(BaseModel):
    test_cases: list[TestCaseIn]


class NewTestRun(BaseModel):
    job_id: str | None = Field(default=None, description="Run in this job's worktree.")


class PlanEdit(BaseModel):
    """An edited plan: phases in the order they will run, each naming its task; the
    breakdown carries renamed tasks. Missing parts keep the current values."""

    summary: str | None = None
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
) -> FastAPI:
    """Build the app. ``require_auth=False`` (tests, trusted local use) skips login;
    ``dev=True`` allows the Vite dev server's origin (``SLIPWRIGHT_DEV=1``); ``static_dir``
    overrides where the built web UI is looked for (default: ``slipwright/api/static``)."""
    static_dir = STATIC_DIR if static_dir is None else static_dir

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine
        app.state.resume_thread = None
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
        yield
        stop.set()

    from slipwright.api.auth import auth_dependency, require_admin
    from slipwright.api.auth import router as auth_router
    from slipwright.api.settings import router as settings_router

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
    api = APIRouter()
    app.include_router(auth_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")

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

    def _agents(eng: Engine) -> list[AgentSummary]:
        return agent_summaries(
            eng.store.list(),
            eng.seed_profile,
            route=eng.effective_routing,
            assigned=eng.agent_routing,
        )

    def _get(eng: Engine, job_id: str) -> Job:
        try:
            return eng.store.get(job_id)
        except JobNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _get_project(eng: Engine, project_id: str) -> Project:
        try:
            return eng.store.get_project(project_id)
        except ProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _start(eng: Engine, job: Job, background: BackgroundTasks) -> Job:
        job = eng.start(job.id, run=False)
        background.add_task(_resume, eng, job.id)
        return job

    # -- dashboard -----------------------------------------------------------------------

    @api.get("/overview", response_model=Overview)
    def get_overview(request: Request, recent: int = 20) -> Overview:
        """Numbers, pending approvals and recent activity across every project."""
        eng = _engine(request)
        return overview(len(eng.store.list_projects()), eng.store.list(), recent=recent)

    @api.get("/activity", response_model=list[ActivityItem])
    def get_all_activity(
        request: Request, limit: int | None = 50, role: RoleName | None = None
    ) -> list[ActivityItem]:
        return project_activity(_engine(request).store.list(), limit=limit, role=role)

    @api.get("/agents", response_model=list[AgentSummary])
    def get_agents(request: Request) -> list[AgentSummary]:
        """The agent cards: scope, default model routing and how much each has worked."""
        eng = _engine(request)
        return _agents(eng)

    @api.put("/agents/{role}/routing", response_model=AgentSummary)
    def put_agent_routing(role: RoleName, body: AgentRouting, request: Request) -> AgentSummary:
        """Pin an agent to a provider and model. 400 when the provider is unknown, has no
        key, or no model was named -- the job would only fail at its first call."""
        require_admin(request)
        eng = _engine(request)
        try:
            eng.assign_agent(role, body.provider, body.model)
        except (ValueError, ProviderUnavailableError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return next(a for a in _agents(eng) if a.role is role)

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
        eng = _engine(request)
        if body.repo_path is not None and not body.repo_path.is_dir():
            raise HTTPException(
                status_code=400, detail=f"repo_path is not a directory: {body.repo_path}"
            )
        if body.repo_path is None and body.github_repo is None and body.clone_url is None:
            raise HTTPException(
                status_code=400, detail="give a repo_path, a github_repo or a clone_url"
            )
        try:
            return eng.create_project(Project(**body.model_dump()))
        except ProjectCloneError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.get("/projects", response_model=list[Project])
    def list_projects(request: Request) -> list[Project]:
        return _engine(request).store.list_projects()

    @api.get("/projects/{project_id}", response_model=Project)
    def get_project(project_id: str, request: Request) -> Project:
        return _get_project(_engine(request), project_id)

    @api.patch("/projects/{project_id}", response_model=Project)
    def patch_project(project_id: str, body: ProjectPatch, request: Request) -> Project:
        eng = _engine(request)
        project = _get_project(eng, project_id)
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
        eng = _engine(request)
        _get_project(eng, project_id)
        try:
            eng.store.delete_project(project_id)
        except ProjectInUse as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @api.post("/projects/{project_id}/jobs", response_model=Job, status_code=201)
    def create_project_job(
        project_id: str, body: NewProjectJob, request: Request, background: BackgroundTasks
    ) -> Job:
        eng = _engine(request)
        _get_project(eng, project_id)
        return _start(eng, eng.create_job(body.request, project_id=project_id), background)

    @api.get("/projects/{project_id}/jobs", response_model=list[Job])
    def list_project_jobs(project_id: str, request: Request) -> list[Job]:
        eng = _engine(request)
        _get_project(eng, project_id)
        return eng.store.list(project_id)

    @api.get("/projects/{project_id}/board", response_model=Board)
    def get_board(project_id: str, request: Request) -> Board:
        """Epics, stories and tasks of every job whose plan was approved, with statuses."""
        eng = _engine(request)
        _get_project(eng, project_id)
        return project_board(project_id, eng.store.list(project_id))

    @api.get("/projects/{project_id}/pipeline", response_model=Pipeline)
    def get_pipeline(project_id: str, request: Request) -> Pipeline:
        """Every development as a lane of step cards, newest first."""
        eng = _engine(request)
        _get_project(eng, project_id)
        jobs = sorted(eng.store.list(project_id), key=lambda j: j.created_at, reverse=True)
        return pipeline(jobs, project_id=project_id)

    @api.get("/projects/{project_id}/progress", response_model=ProjectProgress)
    def get_progress(project_id: str, request: Request) -> ProjectProgress:
        eng = _engine(request)
        _get_project(eng, project_id)
        return project_progress(project_id, eng.store.list(project_id))

    @api.get("/projects/{project_id}/activity", response_model=list[ActivityItem])
    def get_activity(
        project_id: str, request: Request, limit: int | None = None
    ) -> list[ActivityItem]:
        """Every job's history, newest first; ``index`` addresses the detail endpoint."""
        eng = _engine(request)
        _get_project(eng, project_id)
        return project_activity(eng.store.list(project_id), limit=limit)

    # -- test runs -----------------------------------------------------------------------

    @api.post("/projects/{project_id}/test-runs", response_model=TestRun, status_code=202)
    def start_test_run(
        project_id: str, body: NewTestRun, request: Request, background: BackgroundTasks
    ) -> TestRun:
        """Run the profile's test command on the main checkout, or in a job's worktree."""
        eng = _engine(request)
        _get_project(eng, project_id)
        if body.job_id is not None:
            _get(eng, body.job_id)
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
        _get_project(eng, project_id)
        return eng.store.list_test_runs(project_id, job_id)

    def _get_run(eng: Engine, run_id: str) -> TestRun:
        try:
            return eng.store.get_test_run(run_id)
        except TestRunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @api.get("/test-runs/{run_id}", response_model=TestRun)
    def get_test_run(run_id: str, request: Request) -> TestRun:
        return _get_run(_engine(request), run_id)

    @api.get("/test-runs/{run_id}/output", response_class=PlainTextResponse)
    def get_test_run_output(run_id: str, request: Request) -> str:
        eng = _engine(request)
        return eng.test_run_output(_get_run(eng, run_id))

    # -- jobs ----------------------------------------------------------------------------

    @api.post("/jobs", response_model=Job, status_code=201)
    def create_job(body: NewJob, request: Request, background: BackgroundTasks) -> Job:
        """Start a job straight from a repository path (its project is found or created)."""
        eng = _engine(request)
        if not body.repo_path.is_dir():
            raise HTTPException(
                status_code=400, detail=f"repo_path is not a directory: {body.repo_path}"
            )
        return _start(eng, eng.create_job(body.request, body.repo_path), background)

    @api.get("/jobs", response_model=list[Job])
    def list_jobs(request: Request) -> list[Job]:
        return _engine(request).store.list()

    @api.get("/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str, request: Request) -> Job:
        return _get(_engine(request), job_id)

    @api.delete("/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str, request: Request) -> None:
        """Delete a finished job (worktree, branch, port and rows). Running jobs: 409."""
        eng = _engine(request)
        _get(eng, job_id)
        try:
            eng.delete_job(job_id)
        except JobInProgress as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @api.get("/jobs/{job_id}/history/{index}", response_model=Transition)
    def get_transition(job_id: str, index: int, request: Request) -> Transition:
        """One history entry in full (its ``detail`` holds the diff, log or JSON)."""
        job = _get(_engine(request), job_id)
        if index < 0 or index >= len(job.history):
            raise HTTPException(status_code=404, detail=f"no history entry {index}")
        return job.history[index]

    @api.post("/jobs/approve", response_model=BatchResult)
    def approve_many(body: Batch, request: Request, background: BackgroundTasks) -> BatchResult:
        """Approve several gates at once. Each job is an ordinary approval recorded on
        that job; one that is not at a gate is reported, never the whole batch."""
        eng = _engine(request)
        results: list[BatchOutcome] = []
        for job_id in dict.fromkeys(body.job_ids):
            try:
                _get(eng, job_id)
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
                _get(eng, job_id)
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
        _get(eng, job_id)
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
        _get(eng, job_id)
        try:
            job = eng.reject(job_id, body.feedback, run=False)
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        background.add_task(_resume, eng, job.id)
        return job

    @api.put("/jobs/{job_id}/profile", response_model=Job)
    def set_profile(job_id: str, body: Profile, request: Request) -> Job:
        """Edit the proposed profile while the job awaits its approval."""
        eng = _engine(request)
        _get(eng, job_id)
        try:
            return eng.set_profile(job_id, body)
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @api.put("/jobs/{job_id}/backlog", response_model=Job)
    def set_backlog(job_id: str, body: BacklogEdit, request: Request) -> Job:
        """Edit the proposed backlog while the job awaits its approval."""
        eng = _engine(request)
        _get(eng, job_id)
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
        _get(eng, job_id)
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
        _get(eng, job_id)
        try:
            return eng.set_test_cases(job_id, [c.model_dump() for c in body.test_cases])
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @api.get("/jobs/{job_id}/worklist", response_model=WorkList)
    def get_worklist(job_id: str, request: Request) -> WorkList:
        """What each agent is about to do, grouped by agent: the list the person reads
        before starting a development, and the one they edit at the plan gate."""
        eng = _engine(request)
        return work_list(_get(eng, job_id))

    @api.get("/jobs/{job_id}/result", response_model=JobResult)
    def get_job_result(job_id: str, request: Request) -> JobResult:
        """What the development produced: branch, commits, files and how to get them."""
        eng = _engine(request)
        _get(eng, job_id)  # 404 for an unknown job
        result: JobResult = eng.job_result(job_id)
        return result

    @api.post("/jobs/{job_id}/retry", response_model=Job)
    def retry(
        job_id: str, request: Request, background: BackgroundTasks, body: Retry | None = None
    ) -> Job:
        """Continue a failed job from the step it failed in."""
        eng = _engine(request)
        _get(eng, job_id)
        try:
            job = eng.retry(job_id, run=False, feedback=(body.feedback if body else None))
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail="only a failed job can be retried") from exc
        background.add_task(_resume, eng, job.id)
        return job

    @api.post("/jobs/{job_id}/rerun", response_model=Job)
    def rerun(job_id: str, body: Rerun, request: Request, background: BackgroundTasks) -> Job:
        """Run the tests, or the DevOps step, again on a development that has stopped."""
        eng = _engine(request)
        _get(eng, job_id)
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
        eng = _engine(request)
        _get(eng, job_id)
        try:
            return eng.undo_auto_approval(job_id, body.feedback)
        except NotAwaitingApproval as exc:
            raise HTTPException(
                status_code=409, detail="nothing the supervisor approved is left to undo"
            ) from exc

    @api.post("/jobs/{job_id}/message", response_model=Job)
    def message(job_id: str, body: Message, request: Request) -> Job:
        eng = _engine(request)
        _get(eng, job_id)
        return eng.message(job_id, body.text)

    # -- live events ---------------------------------------------------------------------

    @api.get("/events", include_in_schema=True)
    async def events(
        request: Request,
        project_id: str | None = None,
        limit: int | None = None,
        keepalive_s: float = 15.0,
    ) -> StreamingResponse:
        """Server-sent events: ``job.state``, ``job.data``, ``test_run.state``,
        ``activity`` and ``project``. ``project_id`` filters; ``limit`` closes the
        stream after that many events (for scripts and tests)."""
        eng = _engine(request)
        return StreamingResponse(
            _event_stream(eng, project_id=project_id, limit=limit, keepalive_s=keepalive_s),
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


async def _event_stream(
    engine: Engine, *, project_id: str | None, limit: int | None, keepalive_s: float
) -> AsyncIterator[str]:
    import anyio

    sent = 0
    with engine.events.subscribe() as q:
        yield ": connected\n\n"
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


def _jira_sweeper(engine: Engine, every_s: float, stop: threading.Event) -> None:
    """The PO's round: once after startup (after the jobs resumed), then every hour."""
    stop.wait(5.0)  # let the resumed jobs take their locks first
    while not stop.is_set():
        try:
            engine.jira_sweep()
        except Exception:  # noqa: BLE001 - a sweep must never kill the timer
            log.exception("jira sweep failed")
        stop.wait(every_s)


def _resume_all(engine: Engine) -> None:
    """Resume every persisted job, each in its own thread so in-flight jobs overlap."""
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
