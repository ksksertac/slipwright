from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.schemas import testrun as tr
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import PY, full_engine, full_provider

# a test command that passes only when the checkout contains OK == "yes"
_CHECK_PY = "import sys; print('checking'); sys.exit(open('OK').read().strip() != 'yes')"
CHECK = f'"{PY}" -c "{_CHECK_PY}"'
MISSING = f'"{PY}" -c "print(\'no such test\'); raise SystemExit(3)"'

# --- T6.4 test runs on demand -------------------------------------------------------------


def test_manual_run_captures_exit_code_and_output(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    failing = seed.model_copy(update={"test_cmd": MISSING})
    engine = full_engine(store, worktrees_root, failing, full_provider(failing))
    project = engine.create_project(Project(name="demo", repo_path=repo, profile=failing))

    run = engine.start_test_run(project.id)
    assert run.status is tr.TestRunStatus.RUNNING
    assert run.command == MISSING
    assert run.cwd == repo
    assert [r.id for r in store.list_test_runs(project.id)] == [run.id]

    done = engine.execute_test_run(run.id)
    assert done.status is tr.TestRunStatus.FAILED
    assert done.exit_code == 3
    assert done.finished_at is not None and done.duration_s is not None
    assert done.output_path == engine.test_runs_root / f"{run.id}.log"
    assert "no such test" in engine.test_run_output(done)
    assert engine.test_run_output(done).startswith(f"$ {MISSING}")
    assert store.get_test_run(run.id).status is tr.TestRunStatus.FAILED
    assert engine.execute_test_run(run.id).finished_at == done.finished_at  # idempotent


def test_run_in_a_job_worktree_uses_the_job_profile(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    checking = seed.model_copy(update={"test_cmd": CHECK})
    engine = full_engine(store, worktrees_root, checking, full_provider(checking, phases=1))
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(job.id)  # profile approved (test_cmd = CHECK)

    # main checkout has no OK file -> the project-level run fails
    main = engine.execute_test_run(engine.start_test_run(project.id).id)
    assert main.status is tr.TestRunStatus.FAILED
    assert main.command == CHECK  # newest approved job profile is the project's profile

    job = engine.approve(job.id)  # develops OK=yes, gate passes, qa stage 1
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    mine = engine.execute_test_run(engine.start_test_run(project.id, job.id).id)
    assert mine.status is tr.TestRunStatus.PASSED
    assert mine.cwd == job.worktree_path
    assert "checking" in engine.test_run_output(mine)

    # the build gate run is in the same list, marked as such
    runs = store.list_test_runs(project.id)
    sources = {r.id: r.source for r in runs}
    assert sources[mine.id] is tr.TestRunSource.MANUAL
    gate_runs = [r for r in runs if r.source is tr.TestRunSource.GATE]
    assert len(gate_runs) == 1
    assert gate_runs[0].status is tr.TestRunStatus.PASSED
    assert gate_runs[0].job_id == job.id
    assert "[test: exit 0]" in engine.test_run_output(gate_runs[0])
    assert [r.id for r in store.list_test_runs(project.id, job.id)] == [mine.id, gate_runs[0].id]


def test_failed_gate_runs_are_recorded_too(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    broken = seed.model_copy(update={"test_cmd": MISSING})
    engine = full_engine(store, worktrees_root, broken, full_provider(broken, phases=1))
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert job.state is JobState.FAILED
    runs = store.list_test_runs(project.id, job.id)
    assert [r.status for r in runs] == [tr.TestRunStatus.FAILED] * 3  # three gate attempts
    assert all(r.source is tr.TestRunSource.GATE for r in runs)


def test_run_without_checkout_errors_immediately(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed))
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.create_job("never started", project_id=project.id)  # no worktree yet
    run = engine.start_test_run(project.id, job.id)
    assert run.status is tr.TestRunStatus.ERROR
    assert "no checkout" in (run.note or "")


def test_test_run_endpoints(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    failing = seed.model_copy(update={"test_cmd": MISSING})
    engine = full_engine(store, worktrees_root, failing, full_provider(failing))
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        project = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()
        resp = client.post(f"/api/projects/{project['id']}/test-runs", json={})
        assert resp.status_code == 202, resp.text
        run = resp.json()
        assert run["status"] == "running"  # the response never waits for the command

        # TestClient runs background tasks before returning: the run has finished
        listed = client.get(f"/api/projects/{project['id']}/test-runs").json()
        assert [r["id"] for r in listed] == [run["id"]]
        assert listed[0]["status"] == "failed"
        got = client.get(f"/api/test-runs/{run['id']}").json()
        assert got["exit_code"] == 3
        out = client.get(f"/api/test-runs/{run['id']}/output")
        assert out.status_code == 200
        assert "no such test" in out.text
        assert out.headers["content-type"].startswith("text/plain")

        assert client.get("/api/test-runs/nope").status_code == 404
        assert client.get("/api/test-runs/nope/output").status_code == 404
        assert client.post("/api/projects/nope/test-runs", json={}).status_code == 404
        resp = client.post(f"/api/projects/{project['id']}/test-runs", json={"job_id": "nope"})
        assert resp.status_code == 404

        other = client.post("/api/projects", json={"name": "o", "repo_path": str(repo)}).json()
        job = client.post(f"/api/projects/{other['id']}/jobs", json={"request": "x"}).json()
        resp = client.post(f"/api/projects/{project['id']}/test-runs", json={"job_id": job["id"]})
        assert resp.status_code == 400  # job belongs to another project
        assert (
            client.get(f"/api/projects/{project['id']}/test-runs?job_id={job['id']}").json() == []
        )
