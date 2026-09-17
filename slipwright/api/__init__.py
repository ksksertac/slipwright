"""HTTP surface over the engine.

Phase work never runs inside a request: endpoints persist the transition, return the
job, and hand execution to a background task. On startup the app resumes every job that
was mid-phase when the previous process died.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from slipwright.activity import ActivityItem, ProjectProgress, project_activity, project_progress
from slipwright.board import Board, project_board
from slipwright.engine import Engine, NotAwaitingApproval, ProjectCloneError
from slipwright.schemas.job import Job, Transition
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project, ProjectPatch
from slipwright.schemas.testrun import TestRun
from slipwright.store import JobNotFound, ProjectInUse, ProjectNotFound, TestRunNotFound

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


class Rejection(BaseModel):
    feedback: str = Field(min_length=1)


class Message(BaseModel):
    text: str = Field(min_length=1)


class TestCaseIn(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TestCases(BaseModel):
    test_cases: list[TestCaseIn]


class NewTestRun(BaseModel):
    job_id: str | None = Field(default=None, description="Run in this job's worktree.")


def create_app(
    engine: Engine, *, resume_on_startup: bool = True, require_auth: bool = True
) -> FastAPI:
    """Build the app. ``require_auth=False`` (tests, trusted local use) skips login."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine
        app.state.resume_thread = None
        if resume_on_startup:
            thread = threading.Thread(target=_resume_all, args=(engine,), daemon=True)
            thread.start()
            app.state.resume_thread = thread
        yield

    from slipwright.api.auth import auth_dependency
    from slipwright.api.auth import router as auth_router
    from slipwright.api.ui import router as ui_router

    app = FastAPI(
        title="Slipwright",
        lifespan=lifespan,
        dependencies=[Depends(auth_dependency(enabled=require_auth))],
    )
    app.include_router(auth_router)
    app.include_router(ui_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    def _engine(request: Request) -> Engine:
        eng: Engine = request.app.state.engine
        return eng

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

    # -- projects ------------------------------------------------------------------------

    @app.post("/projects", response_model=Project, status_code=201)
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

    @app.get("/projects", response_model=list[Project])
    def list_projects(request: Request) -> list[Project]:
        return _engine(request).store.list_projects()

    @app.get("/projects/{project_id}", response_model=Project)
    def get_project(project_id: str, request: Request) -> Project:
        return _get_project(_engine(request), project_id)

    @app.patch("/projects/{project_id}", response_model=Project)
    def patch_project(project_id: str, body: ProjectPatch, request: Request) -> Project:
        eng = _engine(request)
        project = _get_project(eng, project_id)
        changes = body.model_dump(exclude_unset=True)
        try:
            updated = project.model_copy(update=changes)
            updated = Project.model_validate(updated.model_dump())  # re-run validators
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return eng.store.update_project(updated)

    @app.delete("/projects/{project_id}", status_code=204)
    def delete_project(project_id: str, request: Request) -> None:
        eng = _engine(request)
        _get_project(eng, project_id)
        try:
            eng.store.delete_project(project_id)
        except ProjectInUse as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/jobs", response_model=Job, status_code=201)
    def create_project_job(
        project_id: str, body: NewProjectJob, request: Request, background: BackgroundTasks
    ) -> Job:
        eng = _engine(request)
        _get_project(eng, project_id)
        return _start(eng, eng.create_job(body.request, project_id=project_id), background)

    @app.get("/projects/{project_id}/jobs", response_model=list[Job])
    def list_project_jobs(project_id: str, request: Request) -> list[Job]:
        eng = _engine(request)
        _get_project(eng, project_id)
        return eng.store.list(project_id)

    @app.get("/projects/{project_id}/board", response_model=Board)
    def get_board(project_id: str, request: Request) -> Board:
        """Epics, stories and tasks of every job whose plan was approved, with statuses."""
        eng = _engine(request)
        _get_project(eng, project_id)
        return project_board(project_id, eng.store.list(project_id))

    @app.get("/projects/{project_id}/progress", response_model=ProjectProgress)
    def get_progress(project_id: str, request: Request) -> ProjectProgress:
        eng = _engine(request)
        _get_project(eng, project_id)
        return project_progress(project_id, eng.store.list(project_id))

    @app.get("/projects/{project_id}/activity", response_model=list[ActivityItem])
    def get_activity(
        project_id: str, request: Request, limit: int | None = None
    ) -> list[ActivityItem]:
        """Every job's history, newest first; ``index`` addresses the detail endpoint."""
        eng = _engine(request)
        _get_project(eng, project_id)
        return project_activity(eng.store.list(project_id), limit=limit)

    # -- test runs -----------------------------------------------------------------------

    @app.post("/projects/{project_id}/test-runs", response_model=TestRun, status_code=202)
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

    @app.get("/projects/{project_id}/test-runs", response_model=list[TestRun])
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

    @app.get("/test-runs/{run_id}", response_model=TestRun)
    def get_test_run(run_id: str, request: Request) -> TestRun:
        return _get_run(_engine(request), run_id)

    @app.get("/test-runs/{run_id}/output", response_class=PlainTextResponse)
    def get_test_run_output(run_id: str, request: Request) -> str:
        eng = _engine(request)
        return eng.test_run_output(_get_run(eng, run_id))

    # -- jobs ----------------------------------------------------------------------------

    @app.post("/jobs", response_model=Job, status_code=201)
    def create_job(body: NewJob, request: Request, background: BackgroundTasks) -> Job:
        """Start a job straight from a repository path (its project is found or created)."""
        eng = _engine(request)
        if not body.repo_path.is_dir():
            raise HTTPException(
                status_code=400, detail=f"repo_path is not a directory: {body.repo_path}"
            )
        return _start(eng, eng.create_job(body.request, body.repo_path), background)

    @app.get("/jobs", response_model=list[Job])
    def list_jobs(request: Request) -> list[Job]:
        return _engine(request).store.list()

    @app.get("/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str, request: Request) -> Job:
        return _get(_engine(request), job_id)

    @app.get("/jobs/{job_id}/history/{index}", response_model=Transition)
    def get_transition(job_id: str, index: int, request: Request) -> Transition:
        """One history entry in full (its ``detail`` holds the diff, log or JSON)."""
        job = _get(_engine(request), job_id)
        if index < 0 or index >= len(job.history):
            raise HTTPException(status_code=404, detail=f"no history entry {index}")
        return job.history[index]

    @app.post("/jobs/{job_id}/approve", response_model=Job)
    def approve(job_id: str, request: Request, background: BackgroundTasks) -> Job:
        eng = _engine(request)
        _get(eng, job_id)
        try:
            job = eng.approve(job_id, run=False)
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        background.add_task(_resume, eng, job.id)
        return job

    @app.post("/jobs/{job_id}/reject", response_model=Job)
    def reject(job_id: str, body: Rejection, request: Request, background: BackgroundTasks) -> Job:
        eng = _engine(request)
        _get(eng, job_id)
        try:
            job = eng.reject(job_id, body.feedback, run=False)
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        background.add_task(_resume, eng, job.id)
        return job

    @app.put("/jobs/{job_id}/tests", response_model=Job)
    def set_tests(job_id: str, body: TestCases, request: Request) -> Job:
        """Edit the proposed test list while the job awaits its approval."""
        eng = _engine(request)
        _get(eng, job_id)
        try:
            return eng.set_test_cases(job_id, [c.model_dump() for c in body.test_cases])
        except NotAwaitingApproval as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/jobs/{job_id}/message", response_model=Job)
    def message(job_id: str, body: Message, request: Request) -> Job:
        eng = _engine(request)
        _get(eng, job_id)
        return eng.message(job_id, body.text)

    return app


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
]
