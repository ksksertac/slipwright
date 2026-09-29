"""The account a server starts with.

Somebody who has just run the container should be looking at the thing, not reading a
page that tells them to open a terminal. So an installation with nobody in it makes one
account and the login page says what it is.

The other half of that bargain is that nobody forgets: it exists only while the database
is empty, it is announced at every start, the interface carries a banner until the
password changes, and an installation that should not have it can say so.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.firstrun import NAME, PASSWORD, default_admin_still_open, ensure_default_admin
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8900, end=8999)),
        seed_profile=seed,
    )


def _serving(engine: Engine, **kw: object) -> Iterator[TestClient]:
    kw.setdefault("default_admin_wanted", True)  # what the server that serves asks for
    app = create_app(engine, resume_on_startup=False, require_auth=True, **kw)  # type: ignore[arg-type]
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    yield from _serving(engine)


def test_a_server_with_nobody_in_it_makes_an_account_and_says_so(
    client: TestClient, store: JobStore
) -> None:
    told = client.get("/api/auth/first-run").json()
    assert told["default_admin"] is True
    assert (told["username"], told["password"]) == (NAME, PASSWORD)

    signed_in = client.post("/api/auth/login", json={"username": NAME, "password": PASSWORD})
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["is_admin"] is True, "the account somebody sets the server up with"


def test_it_stops_saying_so_the_moment_the_password_changes(
    client: TestClient, store: JobStore
) -> None:
    """The banner is the price of a published default, and it has to come down by itself."""
    client.post("/api/auth/login", json={"username": NAME, "password": PASSWORD})
    me = client.get("/api/auth/me").json()
    changed = client.put(
        f"/api/users/{me['id']}/password", json={"password": "something of my own"}
    )
    assert changed.status_code in (200, 204), changed.text

    assert default_admin_still_open(store) is False
    told = client.get("/api/auth/first-run").json()
    assert told["default_admin"] is False
    assert told["password"] == "", "never said again once it is not true"


def test_an_installation_that_already_has_somebody_is_left_alone(
    engine: Engine, store: JobStore
) -> None:
    """A server with accounts has an owner. Handing out a known password to somebody
    else's installation is the opposite of helping."""
    store.create_user("ada", "correct horse")
    assert ensure_default_admin(store) is False
    assert [u.username for u in store.list_users()] == ["ada"]


def test_a_server_can_refuse_the_starting_account(engine: Engine, store: JobStore) -> None:
    """What a server open to the internet sets, along with everything else it must."""
    assert ensure_default_admin(store, wanted=False) is False
    assert store.list_users() == []

    with TestClient(
        create_app(engine, resume_on_startup=False, require_auth=True, default_admin_wanted=False)
    ) as client:
        assert store.list_users() == []
        # and the page says the other thing instead: make the first account yourself
        assert client.get("/api/auth/first-run").json()["default_admin"] is False
        assert client.get("/api/auth/me").status_code == 503
