"""T11 — signing up, proving an address, and getting back in.

The flows that turn a private installation into one strangers can join. They are tested
against the outbox transport, so no SMTP server is involved and the letter's link is read
straight out of the database.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.auth import UserStatus
from slipwright.engine import Engine
from slipwright.mail import read_outbox
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

BASE = "https://slipwright.example"


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    eng = Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8700, end=8799)),
        seed_profile=seed,
    )
    eng.update_mail_settings(base_url=BASE)
    return eng


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = create_app(engine, resume_on_startup=False, require_auth=True)
    with TestClient(app) as c:
        yield c


def _link(store: JobStore, to: str) -> str:
    """The token out of the most recent letter sent to an address."""
    letters = read_outbox(store, to=to)
    assert letters, f"no letter was written to {to}"
    for word in letters[0]["body"].split():
        if word.startswith(BASE):
            return word
    raise AssertionError(f"no link in the letter to {to}")


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


# --- signing up --------------------------------------------------------------------------


def test_signing_up_mails_a_link_and_verifying_it_signs_you_in(
    client: TestClient, store: JobStore
) -> None:
    created = client.post(
        "/api/auth/signup",
        json={"email": "Ada@Example.com", "password": "correct horse", "name": "Ada"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "ada@example.com"  # the address is stored lowercased
    assert body["email_verified_at"] is None
    assert body["is_admin"] is False

    # signed in already, but not allowed to start work yet
    assert client.get("/api/auth/me").json()["email"] == "ada@example.com"
    refused = client.post("/api/projects", json={"name": "demo", "repo_path": "."})
    assert refused.status_code == 403
    assert "confirm your email" in refused.json()["detail"]

    link = _link(store, "ada@example.com")
    assert link.startswith(f"{BASE}/verify?token=")
    verified = client.post("/api/auth/verify", json={"token": _token(link)})
    assert verified.status_code == 200
    assert verified.json()["email_verified_at"] is not None

    # and the same link cannot be spent twice
    assert client.post("/api/auth/verify", json={"token": _token(link)}).status_code == 400


def test_the_address_and_the_password_are_checked(client: TestClient) -> None:
    bad = client.post(
        "/api/auth/signup", json={"email": "not-an-address", "password": "longenough"}
    )
    assert bad.status_code == 422

    short = client.post("/api/auth/signup", json={"email": "a@b.co", "password": "short"})
    assert short.status_code == 422
    assert "8 characters" in short.json()["detail"]


def test_one_address_is_one_account(client: TestClient) -> None:
    first = {"email": "ada@example.com", "password": "correct horse"}
    assert client.post("/api/auth/signup", json=first).status_code == 201
    again = client.post("/api/auth/signup", json={**first, "email": "ADA@example.com"})
    assert again.status_code == 409


def test_the_second_letter_invalidates_the_first(client: TestClient, store: JobStore) -> None:
    client.post("/api/auth/signup", json={"email": "ada@example.com", "password": "correct horse"})
    first = _token(_link(store, "ada@example.com"))
    resent = client.post("/api/auth/resend-verification", json={"email": "ada@example.com"})
    assert resent.status_code == 202
    second = _token(_link(store, "ada@example.com"))
    assert second != first
    assert client.post("/api/auth/verify", json={"token": first}).status_code == 400
    assert client.post("/api/auth/verify", json={"token": second}).status_code == 200


# --- logging in --------------------------------------------------------------------------


def test_login_takes_the_address_and_a_suspended_account_cannot(
    client: TestClient, store: JobStore
) -> None:
    client.post("/api/auth/signup", json={"email": "ada@example.com", "password": "correct horse"})
    client.post("/api/auth/logout")

    ok = client.post(
        "/api/auth/login", json={"username": "ADA@example.com", "password": "correct horse"}
    )
    assert ok.status_code == 200

    user = store.find_by_email("ada@example.com")
    assert user is not None
    store.set_status(user.id, UserStatus.SUSPENDED)
    refused = client.post(
        "/api/auth/login", json={"username": "ada@example.com", "password": "correct horse"}
    )
    assert refused.status_code == 401


def test_an_account_made_before_signup_still_logs_in_by_name(
    client: TestClient, store: JobStore
) -> None:
    store.create_user("ada", "correct horse")
    signed = client.post("/api/auth/login", json={"username": "ada", "password": "correct horse"})
    assert signed.status_code == 200
    assert signed.json()["email"] is None
    # nothing to prove, so work is not refused
    assert client.get("/api/projects").status_code == 200


# --- forgetting the password ---------------------------------------------------------------


def test_reset_mails_a_link_that_sets_a_new_password_once(
    client: TestClient, store: JobStore
) -> None:
    client.post("/api/auth/signup", json={"email": "ada@example.com", "password": "correct horse"})
    client.post("/api/auth/verify", json={"token": _token(_link(store, "ada@example.com"))})
    client.post("/api/auth/logout")

    asked = client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    assert asked.status_code == 202
    link = _link(store, "ada@example.com")
    assert link.startswith(f"{BASE}/reset?token=")

    token = _token(link)
    done = client.post("/api/auth/reset-password", json={"token": token, "password": "a new one"})
    assert done.status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # signed in on the new password
    spent = client.post(
        "/api/auth/reset-password", json={"token": token, "password": "x" * 9}
    )
    assert spent.status_code == 400, "a reset link works once"

    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/login", json={"username": "ada@example.com", "password": "correct horse"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"username": "ada@example.com", "password": "a new one"}
        ).status_code
        == 200
    )


def test_forgot_password_says_the_same_thing_for_an_unknown_address(
    client: TestClient, store: JobStore
) -> None:
    known = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == 202
    assert known.json()["detail"] == client.post(
        "/api/auth/forgot-password", json={"email": "also-nobody@example.com"}
    ).json()["detail"]
    assert read_outbox(store, to="nobody@example.com") == []


# --- rationing ------------------------------------------------------------------------------


def test_signups_from_one_address_are_rationed(client: TestClient) -> None:
    payload = {"email": "ada@example.com", "password": "correct horse"}
    seen = {client.post("/api/auth/signup", json=payload).status_code for _ in range(8)}
    assert 429 in seen, "an address that keeps signing up must eventually be refused"
