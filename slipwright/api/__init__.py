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

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from slipwright.engine import Engine, NotAwaitingApproval
from slipwright.schemas.job import Job
from slipwright.store import JobNotFound

log = logging.getLogger(__name__)


class NewJob(BaseModel):
    request: str = Field(min_length=1)
    repo_path: Path


class Rejection(BaseModel):
    feedback: str = Field(min_length=1)


class Message(BaseModel):
    text: str = Field(min_length=1)


class TestCaseIn(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TestCases(BaseModel):
    test_cases: list[TestCaseIn]


def create_app(engine: Engine, *, resume_on_startup: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine
        app.state.resume_thread = None
        if resume_on_startup:
            thread = threading.Thread(target=_resume_all, args=(engine,), daemon=True)
            thread.start()
            app.state.resume_thread = thread
        yield

    app = FastAPI(title="Slipwright", lifespan=lifespan)

    def _engine(request: Request) -> Engine:
        eng: Engine = request.app.state.engine
        return eng

    def _get(eng: Engine, job_id: str) -> Job:
        try:
            return eng.store.get(job_id)
        except JobNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/jobs", response_model=Job, status_code=201)
    def create_job(body: NewJob, request: Request, background: BackgroundTasks) -> Job:
        eng = _engine(request)
        if not body.repo_path.is_dir():
            raise HTTPException(
                status_code=400, detail=f"repo_path is not a directory: {body.repo_path}"
            )
        job = eng.create_job(body.request, body.repo_path)
        job = eng.start(job.id, run=False)
        background.add_task(_resume, eng, job.id)
        return job

    @app.get("/jobs", response_model=list[Job])
    def list_jobs(request: Request) -> list[Job]:
        return _engine(request).store.list()

    @app.get("/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str, request: Request) -> Job:
        return _get(_engine(request), job_id)

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


__all__ = ["Message", "NewJob", "Rejection", "TestCaseIn", "TestCases", "create_app"]
