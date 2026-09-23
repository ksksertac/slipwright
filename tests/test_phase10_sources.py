"""T10.3 — source hosts: GitHub and Bitbucket behind one registry.

The engine never names a vendor: it asks the registry for the host a project belongs to.
These tests drive Bitbucket end to end against a local bare repository and a fake API, so
push, pull request and CI are exercised without the network.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.githost import CiState, NoRemote
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.sources import BITBUCKET, GITHUB, SOURCES, SourceError
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

WORKSPACE = "acme"
REPO = f"{WORKSPACE}/demo"
PR_URL = f"https://bitbucket.org/{REPO}/pull-requests/7"
TOKEN = "bb_token"


class FakeBitbucket:
    """The bits of the Bitbucket API Slipwright uses, answered locally."""

    def __init__(self, token: str = TOKEN) -> None:
        self.token = token
        self.calls: list[tuple[str, str]] = []
        self.pull_requests: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []
        self.user: dict[str, Any] | None = {"username": "bot", "display_name": "Slipwright bot"}

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/2.0")
        self.calls.append((request.method, path))
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": {"message": "bad token"}})
        if path == "/user":
            if self.user is None:  # a workspace token has no user
                return httpx.Response(403, json={"error": {"message": "not a user token"}})
            return httpx.Response(200, json=self.user)
        if path in ("/repositories", f"/repositories/{WORKSPACE}"):
            return httpx.Response(
                200,
                json={
                    "values": [
                        {
                            "full_name": REPO,
                            "is_private": True,
                            "mainbranch": {"name": "main"},
                            "links": {"html": {"href": f"https://bitbucket.org/{REPO}"}},
                            "description": "the demo",
                        }
                    ]
                },
            )
        if path == f"/repositories/{REPO}/pullrequests":
            if request.method == "GET":
                return httpx.Response(200, json={"values": list(self.pull_requests)})
            body = json.loads(request.content)
            created = {"id": 7, "links": {"html": {"href": PR_URL}}, **body}
            self.pull_requests.append(created)
            return httpx.Response(201, json=created)
        if path.startswith(f"/repositories/{REPO}/commit/") and path.endswith("/statuses"):
            return httpx.Response(200, json={"values": list(self.statuses)})
        return httpx.Response(404, json={"error": {"message": f"no route {path}"}})


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def remote(tmp_path: Path, repo: Path) -> Path:
    """A bare repository standing in for the one on Bitbucket, wired as origin."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", f"https://bitbucket.org/{REPO}.git")
    # the host pushes to the URL with the token in it, so that is what has to land here
    for url in (
        f"https://bitbucket.org/{REPO}.git",
        f"https://x-token-auth:{TOKEN}@bitbucket.org/{REPO}.git",
    ):
        _git(repo, "config", "--add", f"url.{bare.as_uri()}.insteadOf", url)
    return bare


def _engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1), git_host=None)
    return engine


def test_every_source_is_described_for_the_settings_page(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    rows = {r.name: r for r in engine.source_settings()}
    assert list(rows) == list(SOURCES)
    assert rows[GITHUB].is_default and not rows[GITHUB].token_set
    assert rows[BITBUCKET].label == "Bitbucket"
    assert rows[BITBUCKET].owner_label == "Workspace"
    assert "access token" in rows[BITBUCKET].token_label.lower()


def test_the_github_page_and_the_sources_page_write_the_same_settings(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    """The GitHub page is the older door onto the same house: a token entered there is the
    token the sources page shows, and the other way round."""
    engine = _engine(store, worktrees_root, seed)
    engine.update_github_settings(token="ghp_old", owner="acme", base_branch="trunk")
    row = next(r for r in engine.source_settings() if r.name == GITHUB)
    assert row.token_set and row.owner == "acme" and row.base_branch == "trunk"
    engine.update_source_settings(GITHUB, owner="other")
    assert engine.github_settings().owner == "other"
    assert engine.github_token() == "ghp_old"


def test_settings_written_before_the_sources_page_are_migrated(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    store.set_setting("github", {"owner": "acme", "base_branch": "trunk"})
    store.set_setting("github.token", "ghp_legacy", secret=True)
    engine = _engine(store, worktrees_root, seed)
    row = next(r for r in engine.source_settings() if r.name == GITHUB)
    assert row.token_set and row.owner == "acme" and row.base_branch == "trunk"
    assert engine.source_token(GITHUB) == "ghp_legacy"


def test_a_host_without_a_token_says_so_instead_of_failing_later(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    with pytest.raises(SourceError) as err:
        engine.source_host(BITBUCKET)
    assert "Bitbucket" in str(err.value) and "BITBUCKET_TOKEN" in str(err.value)


def test_bitbucket_reports_its_identity_and_repositories(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    fake = FakeBitbucket()
    engine.http_transport = fake.transport
    engine.update_source_settings(BITBUCKET, token=fake.token, owner=WORKSPACE)
    host = engine.source_host(BITBUCKET)
    assert host.whoami().login == "bot"
    repos = host.list_repos()
    assert [r.full_name for r in repos] == [REPO]
    assert repos[0].private and repos[0].default_branch == "main"

    fake.user = None  # a workspace token: the workspace is the identity
    assert engine.source_host(BITBUCKET).whoami().login == WORKSPACE


def test_bitbucket_pushes_opens_a_pull_request_and_reads_its_build(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path, remote: Path
) -> None:
    engine = _engine(store, worktrees_root, seed)
    fake = FakeBitbucket()
    engine.http_transport = fake.transport
    engine.update_source_settings(BITBUCKET, token=fake.token, owner=WORKSPACE, base_branch="main")
    host = engine.source_host(BITBUCKET)

    _git(repo, "checkout", "-q", "-b", "slipwright/demo")
    (repo / "new.txt").write_text("work", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "work")
    host.push(repo, "slipwright/demo")
    branches = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=remote,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "slipwright/demo" in branches

    url = host.open_pr(repo, "slipwright/demo", "Add the thing", "why")
    assert url == PR_URL
    body = fake.pull_requests[0]
    assert body["source"]["branch"]["name"] == "slipwright/demo"
    assert body["destination"]["branch"]["name"] == "main"
    assert host.open_pr(repo, "slipwright/demo", "Add the thing", "why") == PR_URL
    assert len(fake.pull_requests) == 1  # the open one is reused, never a second

    assert host.ci_status(repo, "slipwright/demo", url).state is CiState.NONE
    fake.statuses = [{"key": "pipeline", "state": "INPROGRESS", "name": "build"}]
    assert host.ci_status(repo, "slipwright/demo", url).state is CiState.PENDING
    fake.statuses = [{"key": "pipeline", "state": "FAILED", "name": "build", "url": "x"}]
    red = host.ci_status(repo, "slipwright/demo", url)
    assert red.state is CiState.FAILURE and "build" in (red.log or "")
    fake.statuses = [{"key": "pipeline", "state": "SUCCESSFUL", "name": "build"}]
    assert host.ci_status(repo, "slipwright/demo", url).state is CiState.SUCCESS


def test_a_bitbucket_checkout_without_a_remote_is_reported_as_such(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    engine = _engine(store, worktrees_root, seed)
    fake = FakeBitbucket()
    engine.http_transport = fake.transport
    engine.update_source_settings(BITBUCKET, token=fake.token)
    with pytest.raises(NoRemote):
        engine.source_host(BITBUCKET).push(repo, "slipwright/demo")


def test_the_token_never_reaches_the_history(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    """git prints the URL it was given when a push fails; the token must not survive that."""
    engine = _engine(store, worktrees_root, seed)
    fake = FakeBitbucket()
    engine.http_transport = fake.transport
    engine.update_source_settings(BITBUCKET, token="bb_secret_token")
    _git(repo, "remote", "add", "origin", f"https://bitbucket.org/{REPO}.git")
    host = engine.source_host(BITBUCKET)
    with pytest.raises(Exception) as err:  # noqa: PT011 - the git failure, whatever it is
        host.push(repo, "slipwright/demo")
    assert "bb_secret_token" not in str(err.value)


def test_a_project_clones_from_the_host_it_names(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    engine.update_source_settings(BITBUCKET, token="bb_token")
    project = Project(name="demo", source=BITBUCKET, github_repo=REPO)
    assert project.effective_clone_url == f"https://bitbucket.org/{REPO}.git"
    assert engine._authenticated(project.effective_clone_url or "", BITBUCKET) == (
        f"https://x-token-auth:bb_token@bitbucket.org/{REPO}.git"
    )


def test_the_sources_endpoints_connect_test_and_list(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    fake = FakeBitbucket()
    engine.http_transport = fake.transport
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        rows = client.get("/api/settings/sources").json()
        assert [r["name"] for r in rows] == list(SOURCES)
        assert client.post(f"/api/settings/sources/{BITBUCKET}/test").status_code == 400

        resp = client.put(
            f"/api/settings/sources/{BITBUCKET}",
            json={"token": fake.token, "owner": WORKSPACE, "make_default": True},
        )
        assert resp.status_code == 200
        row = next(r for r in resp.json() if r["name"] == BITBUCKET)
        assert row["token_set"] and row["is_default"] and row["owner"] == WORKSPACE
        assert "token" not in row and fake.token not in resp.text

        assert client.post(f"/api/settings/sources/{BITBUCKET}/test").json()["login"] == "bot"
        repos = client.get(f"/api/settings/sources/{BITBUCKET}/repos").json()
        assert [r["full_name"] for r in repos] == [REPO]

        assert client.get("/api/settings/sources/bogus/repos").status_code == 404
        assert client.put("/api/settings/sources/bogus", json={}).status_code == 404

        cleared = client.put(
            f"/api/settings/sources/{BITBUCKET}", json={"clear_token": True}
        ).json()
        assert not next(r for r in cleared if r["name"] == BITBUCKET)["token_set"]
