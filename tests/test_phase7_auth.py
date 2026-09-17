from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright import cli
from slipwright.api import create_app
from slipwright.auth import SESSION_COOKIE, hash_password, verify_password
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore, UsernameTaken, UserNotFound
from tests.pipeline import full_engine, full_provider

# --- T7.1 users and login -----------------------------------------------------------------


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed))


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False)) as c:  # auth on
        yield c


def test_password_hashing_is_salted_and_verifiable() -> None:
    a, b = hash_password("hunter2"), hash_password("hunter2")
    assert a != b and a.startswith("scrypt1$")
    assert verify_password("hunter2", a) and verify_password("hunter2", b)
    assert not verify_password("hunter3", a)
    assert not verify_password("hunter2", "garbage")
    with pytest.raises(ValueError):
        hash_password("")


def test_user_store(store: JobStore) -> None:
    first = store.create_user("ada", "pw1")
    second = store.create_user("bob", "pw2")
    assert first.is_admin and not second.is_admin  # the first user is admin
    assert store.create_user("cy", "pw3", is_admin=True).is_admin
    with pytest.raises(UsernameTaken):
        store.create_user("ada", "x")
    assert store.authenticate("ada", "pw1") == first
    assert store.authenticate("ada", "wrong") is None
    assert store.authenticate("nobody", "pw1") is None
    assert [u.username for u in store.list_users()] == ["ada", "bob", "cy"]

    secret = store.create_session(first.id)
    assert store.session_user(secret) == first
    assert store.session_user("nope") is None
    token, raw = store.create_token(second.id, "laptop")
    assert store.token_user(raw) == second
    assert store.list_tokens(second.id)[0].last_used_at is not None
    store.revoke_token(token.id)
    assert store.token_user(raw) is None

    store.set_password(first.id, "pw9")  # invalidates sessions and tokens
    assert store.session_user(secret) is None
    assert store.authenticate("ada", "pw9") == first
    store.delete_user(second.id)
    with pytest.raises(UserNotFound):
        store.get_user(second.id)


def test_api_answers_503_until_a_user_exists(client: TestClient) -> None:
    resp = client.get("/projects")
    assert resp.status_code == 503
    assert "slipwright user add" in resp.json()["detail"]
    assert client.post("/auth/login", json={"username": "a", "password": "b"}).status_code == 503
    assert client.get("/healthz").status_code == 200  # public


def test_login_logout_and_protected_routes(client: TestClient, engine: Engine) -> None:
    engine.store.create_user("ada", "pw1")
    assert client.get("/projects").status_code == 401
    assert client.get("/auth/me").status_code == 401

    resp = client.post("/auth/login", json={"username": "ada", "password": "nope"})
    assert resp.status_code == 401
    resp = client.post("/auth/login", json={"username": "ada", "password": "pw1"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "ada" and resp.json()["is_admin"] is True
    cookie = resp.cookies.get(SESSION_COOKIE)
    assert cookie
    assert "httponly" in resp.headers["set-cookie"].lower()

    assert client.get("/auth/me").json()["username"] == "ada"  # cookie jar carries it
    assert client.get("/projects").status_code == 200

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401
    assert client.get("/projects").status_code == 401


def test_bearer_tokens(client: TestClient, engine: Engine) -> None:
    ada = engine.store.create_user("ada", "pw1")
    _, secret = engine.store.create_token(ada.id, "cli")
    headers = {"Authorization": f"Bearer {secret}"}
    assert client.get("/auth/me", headers=headers).json()["id"] == ada.id
    assert client.get("/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401

    # issue and revoke tokens over the API
    resp = client.post(f"/users/{ada.id}/tokens", json={"name": "laptop"}, headers=headers)
    assert resp.status_code == 201
    issued = resp.json()
    fresh = {"Authorization": f"Bearer {issued['secret']}"}
    assert client.get("/auth/me", headers=fresh).status_code == 200
    listed = client.get(f"/users/{ada.id}/tokens", headers=headers).json()
    assert [t["name"] for t in listed] == ["cli", "laptop"]
    resp = client.delete(f"/tokens/{issued['token']['id']}", headers=headers)
    assert resp.status_code == 200 and resp.json()["revoked_at"] is not None
    assert (
        client.get("/auth/me", headers={"Authorization": f"Bearer {issued['secret']}"}).status_code
        == 401
    )
    assert client.delete("/tokens/nope", headers=headers).status_code == 404


def test_user_administration(client: TestClient, engine: Engine) -> None:
    admin = engine.store.create_user("ada", "pw1")
    client.post("/auth/login", json={"username": "ada", "password": "pw1"})
    resp = client.post("/users", json={"username": "bob", "password": "pw2"})
    assert resp.status_code == 201
    bob = resp.json()
    assert bob["is_admin"] is False
    assert client.post("/users", json={"username": "bob", "password": "x"}).status_code == 409
    assert [u["username"] for u in client.get("/users").json()] == ["ada", "bob"]
    assert client.put(f"/users/{bob['id']}/password", json={"password": "pw3"}).status_code == 204
    assert client.delete(f"/users/{admin.id}").status_code == 400  # not yourself
    assert client.delete("/users/nope").status_code == 404

    # bob is not an admin: may manage himself only
    with TestClient(create_app(engine, resume_on_startup=False)) as bob_client:
        assert (
            bob_client.post("/auth/login", json={"username": "bob", "password": "pw3"}).status_code
            == 200
        )
        assert bob_client.get("/users").status_code == 403
        assert bob_client.post("/users", json={"username": "x", "password": "y"}).status_code == 403
        assert bob_client.delete(f"/users/{admin.id}").status_code == 403
        assert (
            bob_client.put(f"/users/{admin.id}/password", json={"password": "z"}).status_code == 403
        )
        assert bob_client.get(f"/users/{admin.id}/tokens").status_code == 403
        assert bob_client.post(f"/users/{bob['id']}/tokens", json={}).status_code == 201
        assert (
            bob_client.put(f"/users/{bob['id']}/password", json={"password": "pw4"}).status_code
            == 204
        )
        assert bob_client.get("/auth/me").status_code == 401  # password change ends sessions

    assert client.delete(f"/users/{bob['id']}").status_code == 204
    assert client.get(f"/users/{bob['id']}/tokens").status_code == 404


def test_cli_user_and_token_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("SLIPWRIGHT_STATE_DIR", str(state))
    assert cli.main(["user", "list"]) == 0
    assert "no users" in capsys.readouterr().out
    assert cli.main(["user", "add", "ada", "--password", "pw1"]) == 0
    assert "admin=yes" in capsys.readouterr().out
    assert cli.main(["user", "add", "bob", "--password", "pw2"]) == 0
    assert "admin=no" in capsys.readouterr().out
    assert cli.main(["user", "add", "bob", "--password", "pw2"]) == 1
    assert "already taken" in capsys.readouterr().err
    assert cli.main(["token", "new", "nobody"]) == 1
    capsys.readouterr()
    assert cli.main(["token", "new", "ada"]) == 0
    secret = capsys.readouterr().out.strip()
    with JobStore(state / "jobs.sqlite3") as store:
        user = store.token_user(secret)
        assert user is not None and user.username == "ada"

    # the CLI sends the token as a bearer header
    captured: dict[str, str] = {}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return b"[]"

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            pass

    def fake_urlopen(req: object, timeout: float = 0) -> _Resp:
        captured.update(req.headers)  # type: ignore[attr-defined]
        return _Resp()

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    assert cli.main(["--token", secret, "status"]) == 0
    assert captured.get("Authorization") == f"Bearer {secret}"
