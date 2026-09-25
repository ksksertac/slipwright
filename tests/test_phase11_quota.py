"""T11 — what one account may take of a shared machine.

Model tokens are not rationed: everybody brings their own key, so what they spend is
between them and their vendor. What is rationed is what belongs to the server -- how many
developments run at once, how many projects accumulate, how much disk the checkouts take.

And closing an account has to actually remove what it left behind, or a server fills up
with the work of people who have gone.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.quota import Quota, QuotaExceeded, Quotas, forget_everything
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace
from tests.pipeline import full_provider


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8400, end=8499)),
        seed_profile=seed,
        provider=full_provider(seed, phases=1),
        supervisor_mode="manual",
    )


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


# --- the limits themselves -------------------------------------------------------------------


def test_zero_means_no_limit(engine: Engine, repo: Path) -> None:
    """A single-team installation turns them off and nothing is ever refused."""
    engine.quotas.update(max_running_jobs=0, max_projects=0, max_disk_mb=0)
    assert engine.quotas.limits() == Quota.unlimited()
    for i in range(5):
        engine.store.create_project(Project(name=f"p{i}", repo_path=repo, owner_id="ada"))
    engine.quotas.check_new_project("ada")  # does not raise


def test_projects_are_capped_and_the_example_does_not_count(
    engine: Engine, repo: Path
) -> None:
    engine.quotas.update(max_projects=2)
    engine.store.create_project(
        Project(name="example", repo_path=repo, owner_id="ada", is_demo=True)
    )
    engine.quotas.check_new_project("ada")  # the example is not somebody's own work

    engine.store.create_project(Project(name="one", repo_path=repo, owner_id="ada"))
    engine.store.create_project(Project(name="two", repo_path=repo, owner_id="ada"))
    with pytest.raises(QuotaExceeded) as raised:
        engine.quotas.check_new_project("ada")
    assert raised.value.what == "projects"
    assert "2 of 2" in str(raised.value)

    # and it is one account's limit, not the installation's
    engine.quotas.check_new_project("bob")


def test_running_developments_are_capped(engine: Engine, repo: Path) -> None:
    """Anything not finished counts, including one that has only just been created.

    A job in ``created`` is about to take a thread, a worktree and a container -- it is
    the *starting* that is rationed, so counting it only once it has started would let
    somebody open twenty at once and meet no limit at all.
    """
    engine.quotas.update(max_running_jobs=2)
    project = engine.store.create_project(Project(name="p", repo_path=repo, owner_id="ada"))

    def new(request: str) -> Job:
        return engine.store.create(
            Job(request=request, repo_path=repo, project_id=project.id, owner_id="ada")
        )

    first = new("one")
    engine.quotas.check_new_job("ada")  # one of two

    second = new("two")
    engine.store.update_state(second.id, JobState.BACKLOG)
    with pytest.raises(QuotaExceeded, match="running developments"):
        engine.quotas.check_new_job("ada")

    # finishing one frees the slot again
    engine.store.update_state(first.id, JobState.BACKLOG)
    engine.store.update_state(first.id, JobState.FAILED)
    engine.quotas.check_new_job("ada")

    # and it is one account's limit, not the installation's
    engine.quotas.check_new_job("bob")


def test_disk_is_measured_from_what_is_actually_there(
    store: JobStore, worktrees_root: Path, repo: Path, tmp_path: Path
) -> None:
    quotas = Quotas(store, worktrees_root, tmp_path / "repos")
    project = store.create_project(Project(name="p", repo_path=repo, owner_id="ada"))
    job = store.create(Job(request="x", repo_path=repo, project_id=project.id, owner_id="ada"))

    assert quotas.usage("ada").disk_mb == 0
    tree = worktrees_root / job.id
    tree.mkdir(parents=True)
    (tree / "big.bin").write_bytes(b"0" * (3 * 1024 * 1024))
    assert quotas.usage("ada").disk_mb == 3

    quotas.update(max_disk_mb=2)
    with pytest.raises(QuotaExceeded, match="disk"):
        quotas.check_new_job("ada")


# --- over HTTP ---------------------------------------------------------------------------------


def test_the_endpoints_refuse_with_429_and_say_why(client: TestClient, repo: Path) -> None:
    engine: Engine = client.app.state.engine  # type: ignore[attr-defined]
    engine.quotas.update(max_projects=1)

    first = client.post("/api/projects", json={"name": "one", "repo_path": str(repo)})
    assert first.status_code == 201
    second = client.post("/api/projects", json={"name": "two", "repo_path": str(repo)})
    assert second.status_code == 429
    assert "projects" in second.json()["detail"]


def test_you_can_see_what_you_are_using(client: TestClient, repo: Path) -> None:
    client.post("/api/projects", json={"name": "one", "repo_path": str(repo)})
    body = client.get("/api/quota").json()
    assert body["projects"] == 1
    # off by default: an installation that upgrades must not start refusing work it
    # used to allow, so the limits are something a server opts into
    assert body["limits"]["max_projects"] == 0


def test_raising_the_limit_is_an_administrators_decision(client: TestClient) -> None:
    changed = client.put("/api/settings/quota", json={"max_projects": 50})
    assert changed.status_code == 200
    assert changed.json()["max_projects"] == 50


# --- closing an account -------------------------------------------------------------------------


def test_deleting_an_account_removes_what_it_left_behind(
    store: JobStore, worktrees_root: Path, repo: Path, tmp_path: Path
) -> None:
    repos = tmp_path / "repos"
    project = store.create_project(Project(name="p", repo_path=repo, owner_id="ada"))
    job = store.create(Job(request="x", repo_path=repo, project_id=project.id, owner_id="ada"))
    store.update_state(job.id, JobState.BACKLOG)
    store.update_state(job.id, JobState.DONE)

    tree = worktrees_root / job.id
    tree.mkdir(parents=True)
    (tree / "file.txt").write_text("work", encoding="utf-8")
    clone = repos / project.id
    clone.mkdir(parents=True)
    (clone / "README.md").write_text("cloned", encoding="utf-8")

    store.set_setting("providers.anthropic.api_key", "sk-ada", secret=True, user_id="ada")
    store.save_user_page("ada", "backend", "messaging", "ada's rules")
    # somebody else's work, which must survive
    other = store.create_project(Project(name="theirs", repo_path=repo, owner_id="bob"))
    store.set_setting("providers.anthropic.api_key", "sk-bob", secret=True, user_id="bob")

    forget_everything(store, "ada", worktrees=worktrees_root, repos=repos)

    assert store.list_projects("ada") == []
    assert store.list(owner_id="ada") == []
    assert not tree.exists() and not clone.exists()
    assert store.get_setting("providers.anthropic.api_key", user_id="ada") is None
    assert store.user_pages("ada") == []

    assert [p.id for p in store.list_projects("bob")] == [other.id]
    assert store.get_setting("providers.anthropic.api_key", user_id="bob") == "sk-bob"
