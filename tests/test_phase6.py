from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright import cli
from slipwright.api import create_app
from slipwright.engine import Engine, ProjectCloneError
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, load_profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore, ProjectInUse, ProjectNotFound
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
    ws = Workspace(worktrees_root, PortAllocator(start=8300, end=8399))
    eng = Engine(store, ws, seed_profile=seed, provider=provider, supervisor_mode="manual")
    eng.handlers.pop(JobState.ARCHITECTURE, None)  # stop after profile approval
    return eng


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


# --- T6.1 project entity ------------------------------------------------------------------


def test_project_store_crud_and_reopen(tmp_path: Path, repo: Path) -> None:
    db = tmp_path / "p.sqlite3"
    with JobStore(db) as store:
        project = store.create_project(
            Project(name="demo", repo_path=repo, github_repo="acme/demo", jira_project_key="dem")
        )
        assert project.jira_project_key == "DEM"  # normalised
        assert store.get_project(project.id).name == "demo"
        assert [p.id for p in store.list_projects()] == [project.id]
        store.update_project(project.model_copy(update={"description": "hello"}))
    with JobStore(db) as store:
        again = store.get_project(project.id)
        assert again.description == "hello"
        assert again.repo_path == repo
        assert store.find_project_by_repo(repo) is not None
        with pytest.raises(ProjectNotFound):
            store.get_project("nope")


def test_delete_project_refused_while_jobs_run(engine: Engine, repo: Path) -> None:
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.create_job("x", project_id=project.id)
    assert job.project_id == project.id
    assert job.repo_path == repo
    engine.start(job.id)  # awaiting_backlog_approval: not terminal
    with pytest.raises(ProjectInUse):
        engine.store.delete_project(project.id)
    engine.store.update_state(job.id, JobState.FAILED, note="abandoned by test")
    engine.store.delete_project(project.id)
    assert engine.store.list_projects() == []
    assert engine.store.list() == []


def test_create_job_from_repo_path_creates_a_default_project(engine: Engine, repo: Path) -> None:
    a = engine.create_job("first", repo)
    b = engine.create_job("second", repo)
    assert a.project_id == b.project_id
    (project,) = engine.store.list_projects()
    assert project.name == repo.name
    assert engine.store.list(project.id) == [engine.store.get(a.id), engine.store.get(b.id)]


def test_project_seed_profile_overrides_the_engine_default(
    engine: Engine, repo: Path, provider: ScriptedProvider, seed: Profile
) -> None:
    custom = seed.model_copy(update={"language": "elixir"})
    project = engine.create_project(Project(name="ex", repo_path=repo, profile=custom))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    engine.handlers[JobState.ARCHITECTURE] = engine._architecture
    job = engine.approve(job.id)  # the architect is handed the project's seed profile
    assert '"language": "elixir"' in provider.requests[-1].prompt
    assert engine.seed_for(job) == custom


def test_project_without_checkout_is_cloned(engine: Engine, repo: Path) -> None:
    bare = repo.parent / "origin.git"
    subprocess.run(["git", "clone", "--bare", "-q", str(repo), str(bare)], check=True)
    project = engine.create_project(Project(name="cloned", clone_url=str(bare)))
    assert project.repo_path == engine.repos_root / project.id
    assert (project.repo_path / "README.md").exists()
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL

    with pytest.raises(ProjectCloneError):
        engine.create_project(Project(name="bad", clone_url=str(repo.parent / "missing.git")))
    assert Project(name="gh", github_repo="acme/demo").effective_clone_url == (
        "https://github.com/acme/demo.git"
    )


def test_project_validation() -> None:
    with pytest.raises(ValueError):
        Project(name="x", github_repo="not a repo")
    with pytest.raises(ValueError):
        Project(name="x", jira_project_key="1abc")


def test_project_endpoints(client: TestClient, repo: Path, tmp_path: Path) -> None:
    resp = client.post("/api/projects", json={"name": "demo"})
    assert resp.status_code == 400
    resp = client.post("/api/projects", json={"name": "demo", "repo_path": str(tmp_path / "no")})
    assert resp.status_code == 400
    resp = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)})
    assert resp.status_code == 201, resp.text
    project: dict[str, Any] = resp.json()
    assert project["repo_path"] == str(repo)

    assert [p["id"] for p in client.get("/api/projects").json()] == [project["id"]]
    assert client.get(f"/api/projects/{project['id']}").json()["name"] == "demo"
    assert client.get("/api/projects/nope").status_code == 404

    resp = client.patch(f"/api/projects/{project['id']}", json={"jira_project_key": "dem"})
    assert resp.status_code == 200
    assert resp.json()["jira_project_key"] == "DEM"
    assert resp.json()["repo_path"] == str(repo)
    resp = client.patch(f"/api/projects/{project['id']}", json={"github_repo": "bad"})
    assert resp.status_code == 400

    resp = client.post(f"/api/projects/{project['id']}/jobs", json={"request": "add /health"})
    assert resp.status_code == 201
    job = resp.json()
    assert job["project_id"] == project["id"]
    assert client.get(f"/api/projects/{project['id']}/jobs").json()[0]["id"] == job["id"]
    assert client.get(f"/api/jobs/{job['id']}").json()["state"] == "awaiting_backlog_approval"
    assert client.post("/api/projects/nope/jobs", json={"request": "x"}).status_code == 404

    assert client.delete(f"/api/projects/{project['id']}").status_code == 409
    client.post(f"/api/jobs/{job['id']}/approve")  # planning has no handler here: stays put
    assert client.delete("/api/projects/nope").status_code == 404


class _FakeApi:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def __call__(self, base_url: str, method: str, path: str, body: Any = None) -> Any:
        resp = self.client.request(method, path, json=body)
        if resp.status_code >= 400:
            raise cli.ApiError(resp.status_code, resp.json().get("detail", resp.text))
        return resp.json()


def test_cli_project_commands(
    client: TestClient,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "call", _FakeApi(client))
    assert cli.main(["project", "list"]) == 0
    assert "no projects" in capsys.readouterr().out

    assert cli.main(["project", "new", "demo", "--repo", str(repo), "--jira", "dem"]) == 0
    out = capsys.readouterr().out
    project_id = out.split()[0]
    assert "jira=DEM" in out

    assert cli.main(["new", project_id, "add /health"]) == 0
    assert "backlog" in capsys.readouterr().out

    assert cli.main(["project", "show", project_id]) == 0
    out = capsys.readouterr().out
    assert "jobs:" in out and "awaiting_backlog_approval" in out

    assert cli.main(["project", "list"]) == 0
    assert project_id in capsys.readouterr().out


def test_local_repos_lists_the_mounted_checkouts(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path, tmp_path: Path
) -> None:
    from slipwright.config import Settings
    from slipwright.config import build_engine as _build

    root = tmp_path / "mount"
    root.mkdir()
    (root / "plain").mkdir()  # not a repository
    (root / ".hidden").mkdir()
    shutil.copytree(repo, root / "service")  # a git checkout
    engine = Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8300, end=8399)),
        seed_profile=seed,
        provider=canned(seed),
        supervisor_mode="manual",
    )
    assert engine.local_repos() == []  # nothing configured: the form asks for a path
    engine.local_repos_root = root
    listed = engine.local_repos()
    assert [(r["name"], r["is_git"]) for r in listed] == [("service", True), ("plain", False)]
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        body = client.get("/api/local-repos").json()
        assert body["root"] == root.as_posix() and body["repos"][0]["path"].endswith("/service")
        created = client.post(
            "/api/projects", json={"name": "svc", "repo_path": body["repos"][0]["path"]}
        )
        assert created.status_code == 201
        # a plain folder is turned into a repository on create, its files committed
        (root / "plain" / "app.py").write_text("print(1)\n", encoding="utf-8")
        plain = client.post(
            "/api/projects", json={"name": "plain", "repo_path": body["repos"][1]["path"]}
        )
        assert plain.status_code == 201, plain.text
        assert (root / "plain" / ".git").is_dir()
        log = subprocess.run(
            ["git", "-C", str(root / "plain"), "log", "--oneline"], capture_output=True, text=True
        ).stdout
        assert "slipwright: initial import" in log
        assert client.get("/api/local-repos").json()["repos"][1]["is_git"] is True
        job = client.post(f"/api/projects/{plain.json()['id']}/jobs", json={"request": "x"})
        assert job.status_code == 201  # a worktree can be made from it
    settings = Settings.from_env(
        {
            "SLIPWRIGHT_STATE_DIR": str(tmp_path / "st"),
            "SLIPWRIGHT_PROVIDER": "scripted",
            "SLIPWRIGHT_LOCAL_REPOS": str(root),
        }
    )
    built = _build(settings)
    assert built.local_repos_root == root
    built.store.close()
