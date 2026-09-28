"""'Copy path': a checkout inside Docker, spelled so the host's file manager opens it."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.hostpaths import HostPaths
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

SHARE = r"\\wsl.localhost\docker-desktop\mnt\docker-desktop-disk\data\docker\volumes\w\_data"


def test_a_docker_path_becomes_the_hosts_own_spelling() -> None:
    paths = HostPaths([("/work", SHARE), ("/repos", "C:/Users/Asus/Documents/projects")])
    assert paths.to_host("/work/repos/f313") == SHARE + r"\repos\f313"
    assert paths.to_host("/repos/noteapp") == r"C:\Users\Asus\Documents\projects\noteapp"
    assert HostPaths([("/repos", "/Users/ada/code")]).to_host("/repos/x") == "/Users/ada/code/x"


def test_a_path_nothing_covers_is_left_as_it_is() -> None:
    assert HostPaths([("/work", SHARE)]).to_host("/workshop/x") == "/workshop/x"
    assert HostPaths().to_host("/home/ada/app") == "/home/ada/app"
    assert HostPaths([("/work", "")]).to_host("/work/x") == "/work/x"  # unset, not ""


def test_the_project_page_is_given_the_path_to_copy(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    engine = Engine(store, Workspace(worktrees_root, PortAllocator(8950, 8999)), seed_profile=seed)
    engine.host_paths = HostPaths([(repo.parent.as_posix(), "D:\\code")])
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        made = client.post("/api/projects", json={"name": "x", "repo_path": str(repo)})
        assert made.status_code == 201, made.text
        where = client.get(f"/api/projects/{made.json()['id']}/checkout").json()
    assert where["host_path"] == f"D:\\code\\{repo.name}"
    assert where["translated"] is True
