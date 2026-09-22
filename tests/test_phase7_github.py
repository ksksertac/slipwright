from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.githost import GhHost
from slipwright.github import GitHubClient, GitHubError
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.secrets import KEY_ENV, SecretBox, generate_key, load_or_create_key
from slipwright.store import JobStore
from slipwright.workspace import git as g
from tests.fakes import FakeGitHub
from tests.pipeline import full_engine, full_provider

# --- T7.2 settings store and GitHub connection --------------------------------------------


def test_secret_key_comes_from_env_or_state_dir(tmp_path: Path) -> None:
    key = generate_key()
    assert load_or_create_key(tmp_path, {KEY_ENV: key.decode()}) == key
    created = load_or_create_key(tmp_path / "state", {})
    assert (tmp_path / "state" / "secret.key").read_bytes().strip() == created
    assert load_or_create_key(tmp_path / "state", {}) == created  # stable across runs
    box = SecretBox(created)
    assert box.decrypt(box.encrypt("hunter2")) == "hunter2"
    with pytest.raises(ValueError, match="SLIPWRIGHT_SECRET_KEY"):
        SecretBox(generate_key()).decrypt(box.encrypt("x"))


def test_settings_are_encrypted_at_rest(tmp_path: Path) -> None:
    key = generate_key()
    with JobStore(tmp_path / "s.sqlite3", secret_key=key) as store:
        store.set_setting("plain", {"a": 1})
        store.set_setting("github.token", "ghp_abc", secret=True)
        assert store.get_setting("plain") == {"a": 1}
        assert store.get_setting("github.token") == "ghp_abc"
        assert store.get_setting("missing", "dflt") == "dflt"
        assert store.setting_is_set("github.token") and not store.setting_is_set("nope")
        raw = store._conn.execute(
            "SELECT value_json FROM settings WHERE name = 'github.token'"
        ).fetchone()[0]
        assert "ghp_abc" not in raw
        store.set_setting("plain", 2)
        assert store.get_setting("plain") == 2
        store.delete_setting("plain")
        assert store.get_setting("plain") is None
    with JobStore(tmp_path / "s.sqlite3", secret_key=key) as store:
        assert store.get_setting("github.token") == "ghp_abc"
    with (
        JobStore(tmp_path / "s.sqlite3", secret_key=generate_key()) as store,
        pytest.raises(ValueError),
    ):
        store.get_setting("github.token")


def test_github_client_against_fake() -> None:
    gh = FakeGitHub()
    client = GitHubClient("ghp_secret", transport=gh.transport)
    me = client.whoami()
    assert (me.login, me.rate_limit_remaining) == ("octocat", 4999)
    repos = client.list_repos()
    assert [r.full_name for r in repos] == ["octocat/demo", "acme/secret"]
    assert repos[1].private and repos[1].default_branch == "trunk"
    with pytest.raises(GitHubError, match="401"):
        GitHubClient("wrong", transport=gh.transport).whoami()
    with pytest.raises(GitHubError):
        GitHubClient("")


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed))


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_github_settings_endpoints(client: TestClient, engine: Engine) -> None:
    gh = FakeGitHub()
    engine.http_transport = gh.transport

    assert client.get("/api/settings/github").json() == {
        "owner": None,
        "base_branch": "main",
        "token_set": False,
        "token_hint": None,
    }
    assert client.post("/api/settings/github/test").status_code == 400  # nothing stored
    assert client.get("/api/settings/github/repos").status_code == 400

    resp = client.put("/api/settings/github", json={"token": "ghp_secret", "owner": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_set"] is True and body["token_hint"] == "…cret"
    assert body["owner"] == "acme" and "token" not in body
    assert engine.github_token() == "ghp_secret"

    # omitting the token keeps it; other fields change
    resp = client.put("/api/settings/github", json={"base_branch": "develop"})
    assert resp.json()["token_set"] is True and resp.json()["base_branch"] == "develop"

    me = client.post("/api/settings/github/test").json()
    assert me["login"] == "octocat" and me["rate_limit_limit"] == 5000
    repos = client.get("/api/settings/github/repos").json()
    assert [r["full_name"] for r in repos] == ["octocat/demo", "acme/secret"]

    client.put("/api/settings/github", json={"token": "bad"})
    assert client.post("/api/settings/github/test").status_code == 502
    assert client.get("/api/settings/github/repos").status_code == 502

    resp = client.put("/api/settings/github", json={"clear_token": True})
    assert resp.json()["token_set"] is False
    assert engine.github_token() is None
    assert all(call.startswith(("GET /user",)) for call in gh.calls)


def test_settings_writes_are_admin_only(engine: Engine) -> None:
    engine.store.create_user("ada", "pw")  # admin
    engine.store.create_user("bob", "pw")
    with TestClient(create_app(engine, resume_on_startup=False)) as c:
        c.post("/api/auth/login", json={"username": "bob", "password": "pw"})
        assert c.get("/api/settings/github").status_code == 200
        assert c.put("/api/settings/github", json={"owner": "x"}).status_code == 403
        assert c.post("/api/settings/github/test").status_code == 403


def test_gh_host_passes_the_stored_token_to_gh(
    store: JobStore, worktrees_root: Path, seed: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    engine = full_engine(store, worktrees_root, seed, full_provider(seed), git_host=None)
    host = engine.git_host  # built lazily with the store's token getter
    assert isinstance(host, GhHost)
    assert "GH_TOKEN" not in host._env()
    engine.update_github_settings(token="ghp_live")
    env = host._env()
    assert env["GH_TOKEN"] == "ghp_live" and env["GITHUB_TOKEN"] == "ghp_live"
    assert env["PATH"] == os.environ["PATH"]  # the rest of the environment is intact
    engine.update_github_settings(clear_token=True)
    assert "GH_TOKEN" not in host._env()


def test_clone_url_embeds_the_token_only_for_github(engine: Engine) -> None:
    assert engine._authenticated("https://github.com/acme/demo.git") == (
        "https://github.com/acme/demo.git"
    )
    engine.update_github_settings(token="ghp_live")
    assert engine._authenticated("https://github.com/acme/demo.git") == (
        "https://x-access-token:ghp_live@github.com/acme/demo.git"
    )
    assert engine._authenticated("/local/bare.git") == "/local/bare.git"


def test_a_local_checkout_named_with_a_github_repo_can_be_pushed(
    engine: Engine, tmp_path: Path
) -> None:
    """Without this the DevOps role hits ``NoRemote`` and finishes on the branch, and the
    work never reaches GitHub however well GitHub itself is connected."""
    checkout = tmp_path / "myapp"
    checkout.mkdir()
    (checkout / "README.md").write_text("hello", encoding="utf-8")

    plain = engine.create_project(Project(name="plain", repo_path=checkout))
    assert not g.has_remote(checkout)  # nothing named it, so nothing to push to

    linked = engine.update_project(plain.model_copy(update={"github_repo": "acme/myapp"}))
    assert linked.github_repo == "acme/myapp"
    assert g.run(checkout, "remote", "get-url", "origin").stdout.strip() == (
        "https://github.com/acme/myapp.git"
    )

    # the remote is the user's to own: naming a different repository leaves it alone
    engine.update_project(linked.model_copy(update={"github_repo": "acme/elsewhere"}))
    assert g.run(checkout, "remote", "get-url", "origin").stdout.strip() == (
        "https://github.com/acme/myapp.git"
    )


def test_a_new_project_can_name_its_checkout_and_its_github_repo_at_once(
    engine: Engine, tmp_path: Path
) -> None:
    checkout = tmp_path / "fresh"
    checkout.mkdir()
    engine.create_project(Project(name="fresh", repo_path=checkout, github_repo="acme/fresh"))
    assert g.run(checkout, "remote", "get-url", "origin").stdout.strip() == (
        "https://github.com/acme/fresh.git"
    )


def test_push_authenticates_without_writing_the_token_into_the_checkout() -> None:
    host = GhHost(token=None)
    assert host._credentials() == []  # nothing to offer; git falls back to the machine
    host = GhHost(token="ghp_live")
    args = host._credentials()
    assert args[:3] == ["-c", "credential.helper=", "-c"]
    assert "$GH_TOKEN" in args[3] and "ghp_live" not in args[3]
