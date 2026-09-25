from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright import cli
from slipwright.api import create_app
from slipwright.config import Settings, build_engine
from slipwright.engine import Engine
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, load_profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"


@pytest.fixture
def seed() -> Profile:
    return load_profile(EXAMPLE)


@pytest.fixture
def provider(seed: Profile) -> ScriptedProvider:
    return canned(seed)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[JobStore]:
    with JobStore(tmp_path / "jobs.sqlite3") as s:
        yield s


@pytest.fixture
def engine(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider
) -> Engine:
    ws = Workspace(worktrees_root, PortAllocator(start=8400, end=8499))
    eng = Engine(store, ws, seed_profile=seed, provider=provider, supervisor_mode="manual")
    eng.handlers.pop(JobState.ARCHITECTURE, None)  # stop after backlog approval
    return eng


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _new(client: TestClient, repo: Path, request: str = "add /health") -> dict[str, Any]:
    resp = client.post("/api/jobs", json={"request": request, "repo_path": str(repo)})
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def test_post_jobs_starts_job_and_runs_the_po_in_background(
    client: TestClient, repo: Path, provider: ScriptedProvider
) -> None:
    created = _new(client, repo)
    assert created["state"] == "backlog"  # the response never waits for the model

    # TestClient runs background tasks before returning, so the job has moved on
    job = client.get(f"/api/jobs/{created['id']}").json()
    assert job["state"] == "awaiting_backlog_approval"
    assert job["data"]["backlog"]["epics"][0]["stories"][0]["tasks"][0]["id"] == "t1"
    moves = [t["to_state"] for t in job["history"] if t["from_state"] != t["to_state"]]
    assert moves == ["backlog", "awaiting_backlog_approval"]
    assert len(provider.requests) == 1


def test_post_jobs_rejects_missing_repo(client: TestClient, tmp_path: Path) -> None:
    resp = client.post("/api/jobs", json={"request": "x", "repo_path": str(tmp_path / "nope")})
    assert resp.status_code == 400


def test_list_and_get(client: TestClient, repo: Path) -> None:
    a = _new(client, repo, "first")
    b = _new(client, repo, "second")

    listed = client.get("/api/jobs").json()
    assert [j["id"] for j in listed] == [a["id"], b["id"]]
    assert client.get(f"/api/jobs/{a['id']}").json()["request"] == "first"
    assert client.get("/api/jobs/nope").status_code == 404


def test_approve_and_reject_endpoints(
    client: TestClient, repo: Path, provider: ScriptedProvider
) -> None:
    job_id = _new(client, repo)["id"]

    resp = client.post(f"/api/jobs/{job_id}/reject", json={"feedback": "use poetry"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "backlog"
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "awaiting_backlog_approval"
    assert "use poetry" in provider.requests[-1].prompt

    resp = client.post(f"/api/jobs/{job_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["state"] == "architecture"

    # not at a gate any more
    assert client.post(f"/api/jobs/{job_id}/approve").status_code == 409
    assert client.post(f"/api/jobs/{job_id}/reject", json={"feedback": "x"}).status_code == 409
    assert client.post("/api/jobs/nope/approve").status_code == 404


def test_message_endpoint_queues_inbox(client: TestClient, repo: Path) -> None:
    job_id = _new(client, repo)["id"]
    resp = client.post(f"/api/jobs/{job_id}/message", json={"text": "prefer poetry"})
    assert resp.status_code == 200
    inbox = resp.json()["data"]["inbox"]
    assert [m["text"] for m in inbox] == ["prefer poetry"]
    assert inbox[0]["consumed_at"] is None


def test_startup_resumes_jobs_left_mid_phase(
    engine: Engine, repo: Path, provider: ScriptedProvider
) -> None:
    job = engine.create_job("resume me", repo)
    engine.start(job.id, run=False)  # persisted as analyzing, never executed
    assert engine.store.get(job.id).state is JobState.BACKLOG

    with TestClient(create_app(engine, require_auth=False)) as client:
        client.app.state.resume_thread.join(timeout=60)
        assert client.get(f"/api/jobs/{job.id}").json()["state"] == "awaiting_backlog_approval"
    assert len(provider.requests) == 1


# --- config -------------------------------------------------------------------------------


def test_settings_from_env(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "SLIPWRIGHT_STATE_DIR": str(tmp_path / "st"),
            "SLIPWRIGHT_PROVIDER": "scripted",
            "SLIPWRIGHT_PORT": "9000",
            "SLIPWRIGHT_PORT_RANGE": "9100-9200",
        }
    )
    assert settings.db_path == tmp_path / "st" / "jobs.sqlite3"
    # checkouts live outside the state directory: a job's own commands run in one of them
    # and must not be able to reach the key that decrypts every stored credential
    assert settings.worktrees_root == tmp_path / "st-work" / "worktrees"
    assert not settings.work_dir.is_relative_to(settings.state_dir)
    assert settings.provider == "scripted"
    assert settings.url == "http://127.0.0.1:9000"
    assert settings.port_range == (9100, 9200)


def test_build_engine_scripted(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {"SLIPWRIGHT_STATE_DIR": str(tmp_path / "st"), "SLIPWRIGHT_PROVIDER": "scripted"}
    )
    engine = build_engine(settings)
    assert isinstance(engine.provider, ScriptedProvider)
    assert settings.db_path.exists()
    engine.store.close()


# --- cli ----------------------------------------------------------------------------------


class _FakeApi:
    """Routes cli.call() into a TestClient."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def __call__(self, base_url: str, method: str, path: str, body: Any = None) -> Any:
        resp = self.client.request(method, path, json=body)
        if resp.status_code >= 400:
            raise cli.ApiError(resp.status_code, resp.json().get("detail", resp.text))
        return resp.json()


def test_cli_new_status_approve(
    client: TestClient,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "call", _FakeApi(client))

    assert cli.main(["new", str(repo), "add /health"]) == 0
    out = capsys.readouterr().out
    job_id = out.split()[0]
    assert "backlog" in out

    assert cli.main(["status"]) == 0
    assert job_id in capsys.readouterr().out

    assert cli.main(["status", job_id]) == 0
    out = capsys.readouterr().out
    assert "awaiting_backlog_approval" in out
    assert "backlog -> awaiting_backlog_approval" in out

    assert cli.main(["status", job_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == job_id

    assert cli.main(["reject", job_id, "wrong runner"]) == 0
    capsys.readouterr()
    assert cli.main(["approve", job_id]) == 0
    assert "architecture" in capsys.readouterr().out

    assert cli.main(["approve", job_id]) == 1
    assert "HTTP 409" in capsys.readouterr().err
