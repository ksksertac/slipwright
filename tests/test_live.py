import sys
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, load_profile
from slipwright.workspace import LiveEnvError, PortAllocator, Workspace
from slipwright.workspace.live import port_answers

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"
PY = sys.executable


def _profile(run_cmd: str) -> Profile:
    return load_profile(EXAMPLE).model_copy(update={"run_cmd": run_cmd})


# python -m http.server is a real TCP server available everywhere; it logs to stderr.
SERVER_CMD = f'"{PY}" -m http.server {{port}} --bind 127.0.0.1'


@pytest.fixture
def ws(worktrees_root: Path) -> Iterator[Workspace]:
    workspace = Workspace(worktrees_root, PortAllocator(start=8200, end=8299))
    yield workspace
    # belt and braces: never leave servers behind after a test
    for pidfile in workspace.logs_root.glob("*.pid") if workspace.logs_root.exists() else []:
        job_id = pidfile.stem
        workspace.down(Job(id=job_id, request="cleanup", repo_path=Path(".")))


def _created_job(ws: Workspace, repo: Path, run_cmd: str = SERVER_CMD) -> Job:
    job = Job(request="serve", repo_path=repo, profile=_profile(run_cmd))
    return ws.create(job)


def test_up_serves_worktree_on_job_port_and_logs_to_file(
    ws: Workspace, repo: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    job = _created_job(ws, repo)
    assert job.port is not None and job.worktree_path is not None
    assert not port_answers(job.port)

    pid = ws.up(job, health_timeout=20)

    try:
        assert pid > 0
        assert port_answers(job.port)
        assert ws.is_running(job)
        # it is *this* worktree being served: the fixture repo's README is there
        body = urllib.request.urlopen(f"http://127.0.0.1:{job.port}/README.md", timeout=5).read()
        assert body == b"# fixture repo\n"
    finally:
        ws.down(job)

    log = ws.log_path(job).read_text(encoding="utf-8")
    assert log.startswith(f'$ "{PY}" -m http.server {job.port}')
    assert "GET /README.md" in log  # http.server request logging landed in the file
    out, err = capfd.readouterr()
    assert "GET /README.md" not in out + err  # ...and not on our stdout/stderr


def test_down_frees_port_and_is_idempotent(ws: Workspace, repo: Path) -> None:
    job = _created_job(ws, repo)
    assert job.port is not None
    ws.up(job, health_timeout=20)
    assert port_answers(job.port)

    ws.down(job)
    assert not port_answers(job.port)
    assert not ws.is_running(job)
    ws.down(job)  # nothing running: no error
    ws.down(Job(request="never up", repo_path=repo))  # never started: no error


def test_two_jobs_serve_their_own_worktrees_concurrently(ws: Workspace, repo: Path) -> None:
    a = _created_job(ws, repo)
    b = _created_job(ws, repo)
    assert a.worktree_path and b.worktree_path and a.port and b.port
    (a.worktree_path / "who.txt").write_text("a", encoding="utf-8")
    (b.worktree_path / "who.txt").write_text("b", encoding="utf-8")

    ws.up(a, health_timeout=20)
    ws.up(b, health_timeout=20)
    try:
        get = lambda port: urllib.request.urlopen(  # noqa: E731
            f"http://127.0.0.1:{port}/who.txt", timeout=5
        ).read()
        assert get(a.port) == b"a"
        assert get(b.port) == b"b"
    finally:
        ws.down(a)
        ws.down(b)
    assert ws.log_path(a) != ws.log_path(b)


def test_up_fails_fast_when_run_cmd_exits(ws: Workspace, repo: Path) -> None:
    cmd = f'"{PY}" -c "import sys; print(\'boom on port {{port}}\'); sys.exit(3)"'
    job = _created_job(ws, repo, run_cmd=cmd)
    with pytest.raises(LiveEnvError, match="exited with 3") as excinfo:
        ws.up(job, health_timeout=20)
    assert f"boom on port {job.port}" in excinfo.value.log_tail
    assert not ws.is_running(job)
    assert not (ws.logs_root / f"{job.id}.pid").exists()


def test_up_times_out_and_kills_when_port_never_answers(ws: Workspace, repo: Path) -> None:
    cmd = f'"{PY}" -c "import time; print(\'sleeping\', flush=True); time.sleep(60)"'
    job = _created_job(ws, repo, run_cmd=cmd)
    with pytest.raises(LiveEnvError, match="did not answer within 1s"):
        ws.up(job, health_timeout=1)
    assert not ws.is_running(job)
    assert not (ws.logs_root / f"{job.id}.pid").exists()


def test_up_requires_profile_and_workspace(ws: Workspace, repo: Path) -> None:
    with pytest.raises(LiveEnvError, match="no profile"):
        ws.up(Job(request="x", repo_path=repo))
    with pytest.raises(LiveEnvError, match="no worktree/port"):
        ws.up(Job(request="x", repo_path=repo, profile=_profile(SERVER_CMD)))


def test_destroy_tears_down_running_environment(ws: Workspace, repo: Path) -> None:
    job = _created_job(ws, repo)
    port = job.port
    assert port is not None
    ws.up(job, health_timeout=20)
    ws.destroy(job)
    assert not port_answers(port)
    assert job.port is None and job.worktree_path is None
    assert ws.ports.reserved == frozenset()


def test_down_works_from_a_fresh_workspace_after_restart(worktrees_root: Path, repo: Path) -> None:
    first = Workspace(worktrees_root, PortAllocator(start=8200, end=8299))
    job = _created_job(first, repo)
    assert job.port is not None
    first.up(job, health_timeout=20)

    # "restart": new Workspace object, same roots; the PID file is the only link
    second = Workspace(worktrees_root, PortAllocator(start=8200, end=8299))
    assert second.is_running(job)
    second.down(job)
    assert not port_answers(job.port)
