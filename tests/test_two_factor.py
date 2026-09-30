"""Two-step sign-in: a code from an authenticator app after the password.

Optional and per person. What matters is what somebody would notice: a password alone
stops opening the account once it is on, a code works once, a lost phone has a way back,
and a letter's link does not walk around the second step.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from slipwright import twofactor
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.mail import read_outbox
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.store.schema import users
from slipwright.workspace import PortAllocator, Workspace

BASE = "https://slipwright.example"
ADA = {"username": "ada@example.com", "password": "correct horse"}


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


def _signed_up(client: TestClient) -> None:
    made = client.post(
        "/api/auth/signup", json={"email": ADA["username"], "password": ADA["password"]}
    )
    assert made.status_code == 201, made.text


def _turned_on(client: TestClient) -> tuple[str, list[str]]:
    """Two-step sign-in set up the way the wizard does it: scan, then show a code back."""
    setup = client.post("/api/auth/two-factor/setup")
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["qr"].startswith("data:image/svg+xml")
    code = twofactor.code_at(secret, twofactor.current_step())
    on = client.post("/api/auth/two-factor/enable", json={"code": code})
    assert on.status_code == 200, on.text
    return secret, on.json()["recovery_codes"]


def _next_code(secret: str) -> str:
    """A code the app will show in a moment: the one it showed now is spent."""
    return twofactor.code_at(secret, twofactor.current_step() + 1)


def test_the_codes_are_the_ones_an_authenticator_app_shows() -> None:
    # RFC 6238's own test vector, cut to six digits: the secret "12345678901234567890"
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert twofactor.code_at(secret, 59 // 30) == "287082"
    assert twofactor.code_at(secret, 1111111109 // 30) == "081804"
    uri = twofactor.provisioning_uri(secret, "ada@example.com")
    assert uri.startswith("otpauth://totp/Slipwright:ada@example.com?")
    assert f"secret={secret}" in uri and "issuer=Slipwright" in uri


def test_nothing_changes_until_somebody_turns_it_on(client: TestClient) -> None:
    _signed_up(client)
    assert client.get("/api/auth/two-factor").json() == {
        "enabled": False,
        "recovery_codes_left": 0,
    }
    # a setup started and abandoned leaves signing in exactly as it was
    client.post("/api/auth/two-factor/setup")
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json=ADA).status_code == 200


def test_a_wrong_code_does_not_turn_it_on(client: TestClient) -> None:
    _signed_up(client)
    client.post("/api/auth/two-factor/setup")
    refused = client.post("/api/auth/two-factor/enable", json={"code": "000000"})
    assert refused.status_code == 400
    assert client.get("/api/auth/me").json()["two_factor"] is False


def test_once_on_the_password_alone_no_longer_signs_in(client: TestClient) -> None:
    _signed_up(client)
    secret, _ = _turned_on(client)
    assert client.get("/api/auth/me").json()["two_factor"] is True
    client.post("/api/auth/logout")

    asked = client.post("/api/auth/login", json=ADA)
    assert asked.status_code == 401
    assert asked.headers["X-Slipwright-Two-Factor"] == "required"
    assert client.get("/api/auth/me").status_code == 401, "no session from the password alone"

    wrong = client.post("/api/auth/login", json={**ADA, "code": "123456"})
    assert wrong.status_code == 401
    assert wrong.headers["X-Slipwright-Two-Factor"] == "invalid"

    code = _next_code(secret)
    assert client.post("/api/auth/login", json={**ADA, "code": code}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_a_code_opens_the_account_once(client: TestClient) -> None:
    _signed_up(client)
    secret, _ = _turned_on(client)
    client.post("/api/auth/logout")
    code = _next_code(secret)
    assert client.post("/api/auth/login", json={**ADA, "code": code}).status_code == 200
    client.post("/api/auth/logout")
    again = client.post("/api/auth/login", json={**ADA, "code": code})
    assert again.status_code == 401, "a code read over somebody's shoulder is already spent"


def test_a_recovery_code_gets_somebody_in_once(client: TestClient, store: JobStore) -> None:
    _signed_up(client)
    _, recovery = _turned_on(client)
    assert len(recovery) == twofactor.RECOVERY_CODES
    client.post("/api/auth/logout")

    # copied off paper: lower case, no dash, stray spaces
    typed = recovery[0].replace("-", " ").lower()
    assert client.post("/api/auth/login", json={**ADA, "code": typed}).status_code == 200
    assert client.get("/api/auth/two-factor").json()["recovery_codes_left"] == 7
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={**ADA, "code": recovery[0]}).status_code == 401


def test_turning_it_off_asks_for_the_password_and_a_code(client: TestClient) -> None:
    _signed_up(client)
    secret, _ = _turned_on(client)
    code = _next_code(secret)
    wrong_password = client.post(
        "/api/auth/two-factor/disable", json={"password": "not it", "code": code}
    )
    assert wrong_password.status_code == 400
    off = client.post(
        "/api/auth/two-factor/disable", json={"password": ADA["password"], "code": code}
    )
    assert off.status_code == 200 and off.json()["two_factor"] is False
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json=ADA).status_code == 200


def test_a_reset_link_changes_the_password_but_does_not_sign_in_around_the_code(
    client: TestClient, store: JobStore
) -> None:
    """The link proves the mailbox, not the phone."""
    _signed_up(client)
    secret, _ = _turned_on(client)
    client.post("/api/auth/logout")
    client.post("/api/auth/forgot-password", json={"email": ADA["username"]})
    letter = read_outbox(store, to=ADA["username"])[0]["body"]
    link = next(w for w in letter.split() if w.startswith(f"{BASE}/reset"))
    token = parse_qs(urlparse(link).query)["token"][0]

    done = client.post("/api/auth/reset-password", json={"token": token, "password": "a new one"})
    assert done.status_code == 401
    assert done.headers["X-Slipwright-Two-Factor"] == "required"
    assert client.get("/api/auth/me").status_code == 401

    fresh = {"username": ADA["username"], "password": "a new one", "code": _next_code(secret)}
    assert client.post("/api/auth/login", json=fresh).status_code == 200


def test_an_administrator_can_take_it_off_somebody_who_lost_their_phone(
    client: TestClient, store: JobStore
) -> None:
    _signed_up(client)  # the first account: the administrator
    admin = store.find_by_email(ADA["username"])
    assert admin is not None
    bob = store.create_user("bob", "bobs password", email="bob@example.com", verified=True)
    secret = store.start_two_factor(bob.id)
    assert store.enable_two_factor(bob.id, twofactor.code_at(secret, twofactor.current_step()))
    assert store.get_user(bob.id).two_factor

    reset = client.delete(f"/api/users/{bob.id}/two-factor")
    assert reset.status_code == 200 and reset.json()["two_factor"] is False
    client.post("/api/auth/logout")
    bob_in = client.post(
        "/api/auth/login", json={"username": "bob@example.com", "password": "bobs password"}
    )
    assert bob_in.status_code == 200


def test_the_setup_wizard_offers_it_without_requiring_it(client: TestClient) -> None:
    _signed_up(client)
    steps = {s["key"]: s for s in client.get("/api/onboarding").json()["steps"]}
    assert steps["two_factor"] == {"key": "two_factor", "done": False, "required": False}
    _turned_on(client)
    steps = {s["key"]: s for s in client.get("/api/onboarding").json()["steps"]}
    assert steps["two_factor"]["done"] is True


def test_the_secret_is_not_stored_in_the_clear(client: TestClient, store: JobStore) -> None:
    _signed_up(client)
    secret, _ = _turned_on(client)
    with store.db.connect() as conn:
        stored = conn.execute(select(users.c.totp_secret)).scalar_one()
    assert stored and secret not in stored


def test_a_database_from_before_comes_through_with_it_off(tmp_path: Path) -> None:
    """Nothing is turned on for anybody: an upgrade must not change how people sign in."""
    from alembic import command
    from sqlalchemy import text

    from slipwright.store.db import Database
    from slipwright.store.migrate import _config, migrate
    from slipwright.store.schema import metadata

    db = Database(str(tmp_path / "old.sqlite3"))
    try:
        metadata.create_all(db.engine)
        with db.begin() as conn:
            for column in ("totp_secret", "totp_enabled_at", "totp_last_step", "totp_recovery"):
                conn.execute(text(f"ALTER TABLE users DROP COLUMN {column}"))
            # and what the revisions after it add, since those replay on top (0010)
            conn.execute(text("DROP TABLE attachments"))
            conn.execute(
                text(
                    "INSERT INTO users (id, username, email, status, password_hash,"
                    " is_admin, created_at) VALUES ('u1', 'Ada', 'ada@acme.com', 'active',"
                    " 'x', 1, '2026-01-01T00:00:00+00:00')"
                )
            )
        command.stamp(_config(db), "0008_notify")

        migrate(db)

        with db.connect() as conn:
            row = conn.execute(select(users.c.username, users.c.totp_enabled_at)).one()
        assert tuple(row) == ("Ada", None)
    finally:
        db.dispose()
