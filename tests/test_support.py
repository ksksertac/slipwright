"""The support desk and the email settings behind it.

Two things are being pinned down. One: a support request is kept whatever mail does, and
the row says where the letter went. Two: the email page is the installation's, so only an
administrator may read or change it, and the stored password never comes back out.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.mail import MailError, MailSettings, read_outbox
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.support import SupportDesk, TooManyRequests
from tests.pipeline import full_engine, full_provider


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed))


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False)) as c:  # auth on
        yield c


def _admin(client: TestClient, store: JobStore) -> None:
    """An administrator with a confirmed address, signed in."""
    user = store.create_user("ada", "pw1", is_admin=True, email="ada@example.com")
    store.mark_email_verified(user.id)
    resp = client.post("/api/auth/login", json={"username": "ada", "password": "pw1"})
    assert resp.status_code == 200, resp.text


class Refusing:
    """A mailer whose server is down."""

    def send(self, to: str, subject: str, body: str) -> None:
        raise MailError("connection refused")


class Collecting:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


# -- who a request reaches -------------------------------------------------------------


def test_the_support_address_wins_over_the_administrators(store: JobStore) -> None:
    admin = store.create_user("ada", "pw", is_admin=True, email="ada@example.com")
    store.mark_email_verified(admin.id)
    desk = SupportDesk(store, Collecting(), MailSettings(support_email="help@example.com"))
    assert desk.recipients() == ["help@example.com"]

    several = SupportDesk(
        store, Collecting(), MailSettings(support_email="a@example.com, b@example.com")
    )
    assert several.recipients() == ["a@example.com", "b@example.com"]


def test_with_no_support_address_it_falls_back_to_confirmed_admins(store: JobStore) -> None:
    admin = store.create_user("ada", "pw", is_admin=True, email="ada@example.com")
    store.mark_email_verified(admin.id)
    store.create_user("unconfirmed", "pw", is_admin=True, email="bob@example.com")
    store.create_user("member", "pw", is_admin=False, email="cy@example.com")
    desk = SupportDesk(store, Collecting(), MailSettings())
    assert desk.recipients() == ["ada@example.com"]


# -- taking a request ------------------------------------------------------------------


def test_a_request_survives_a_mail_server_that_is_down(store: JobStore) -> None:
    admin = store.create_user("ada", "pw", is_admin=True, email="ada@example.com")
    store.mark_email_verified(admin.id)
    desk = SupportDesk(store, Refusing(), MailSettings(support_email="help@example.com"))
    row = desk.submit(email="ken@example.com", subject="Cannot log in", message="It says 500.")
    assert row["delivery"] == "failed"
    assert "connection refused" in row["delivery_error"]
    # the question itself is kept, which is the whole point
    kept = store.list_support_requests()
    assert [r["subject"] for r in kept] == ["Cannot log in"]
    assert kept[0]["message"] == "It says 500."


def test_a_sent_request_carries_the_senders_address_for_the_reply(store: JobStore) -> None:
    mailer = Collecting()
    desk = SupportDesk(
        store,
        mailer,
        MailSettings(
            transport="smtp", host="mail.example.com", support_email="help@example.com"
        ),
    )
    row = desk.submit(
        email="ken@example.com",
        subject="Billing",
        message="Charged twice.",
        name="Ken",
        category="billing",
        lang="en",
    )
    assert row["delivery"] == "sent" and row["sent_to"] == "help@example.com"
    to_support, receipt = mailer.sent
    assert to_support[0] == "help@example.com"
    assert to_support[1] == "[Slipwright support] Billing"
    assert "ken@example.com" in to_support[2] and "Charged twice." in to_support[2]
    # and the sender is told it arrived
    assert receipt[0] == "ken@example.com"
    assert row["id"] in receipt[2]


def test_with_no_smtp_the_request_lands_in_the_outbox_and_says_so(
    store: JobStore, engine: Engine
) -> None:
    admin = store.create_user("ada", "pw", is_admin=True, email="ada@example.com")
    store.mark_email_verified(admin.id)
    row = engine.support().submit(email="ken@example.com", subject="Hello", message="Anyone?")
    assert row["delivery"] == "outbox"
    # no receipt is written: the outbox is for an admin to read, not the sender
    assert [letter["to_address"] for letter in read_outbox(store)] == ["ada@example.com"]


def test_a_request_with_nowhere_to_go_is_still_kept(store: JobStore) -> None:
    desk = SupportDesk(store, Collecting(), MailSettings())  # no support address, no admins
    row = desk.submit(email="ken@example.com", subject="Hello", message="Anyone?")
    assert row["delivery"] == "failed"
    assert "no support address" in row["delivery_error"]


def test_requests_are_rationed(store: JobStore) -> None:
    desk = SupportDesk(store, Collecting(), MailSettings(support_email="help@example.com"))
    for _ in range(10):
        desk.submit(email="ken@example.com", subject="s", message="m", user_id="u1")
    with pytest.raises(TooManyRequests):
        desk.submit(email="ken@example.com", subject="s", message="m", user_id="u1")


# -- over HTTP -------------------------------------------------------------------------


def test_anybody_signed_in_may_write_and_reads_only_their_own(
    client: TestClient, store: JobStore
) -> None:
    admin = store.create_user("ada", "pw1", is_admin=True, email="ada@example.com")
    store.mark_email_verified(admin.id)
    store.create_user("ken", "pw2", email="ken@example.com")

    client.post("/api/auth/login", json={"username": "ken", "password": "pw2"})
    made = client.post(
        "/api/support",
        json={
            "subject": "Cannot start a job",
            "message": "Nothing happens.",
            "category": "problem",
        },
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["email"] == "ken@example.com" and body["delivery"] == "outbox"

    mine = client.get("/api/support/mine")
    assert [r["subject"] for r in mine.json()] == ["Cannot start a job"]
    # the whole list is somebody else's business
    assert client.get("/api/support").status_code == 403

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "ada", "password": "pw1"})
    everything = client.get("/api/support")
    assert everything.status_code == 200
    assert [r["subject"] for r in everything.json()] == ["Cannot start a job"]

    closed = client.put(f"/api/support/{body['id']}/status", json={"status": "closed"})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"


def test_an_unverified_account_may_still_ask_for_help(client: TestClient, store: JobStore) -> None:
    """The likeliest reason to write is that the letter never came."""
    store.create_user("ada", "pw1", is_admin=True, email="ada@example.com")
    store.create_user("ken", "pw2", email="ken@example.com")  # not verified
    client.post("/api/auth/login", json={"username": "ken", "password": "pw2"})
    made = client.post("/api/support", json={"subject": "No letter", "message": "Never arrived."})
    assert made.status_code == 201, made.text


# -- the email settings page -----------------------------------------------------------


def test_the_email_page_is_admin_only(client: TestClient, store: JobStore) -> None:
    store.create_user("ada", "pw1", is_admin=True, email="ada@example.com")
    store.create_user("ken", "pw2", email="ken@example.com")
    client.post("/api/auth/login", json={"username": "ken", "password": "pw2"})
    assert client.get("/api/settings/mail").status_code == 403
    assert client.put("/api/settings/mail", json={"host": "x"}).status_code == 403
    assert client.get("/api/settings/mail/outbox").status_code == 403


def test_the_smtp_password_is_never_read_back(client: TestClient, store: JobStore) -> None:
    _admin(client, store)
    saved = client.put(
        "/api/settings/mail",
        json={
            "transport": "smtp",
            "host": "smtp.example.com",
            "port": 465,
            "security": "ssl",
            "username": "postmaster",
            "password": "s3cret-token",
            "from_address": "no-reply@example.com",
            "support_email": "help@example.com",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert "password" not in body
    assert body["password_set"] is True and body["password_hint"] == "…oken"
    assert body["configured"] is True
    assert body["support_recipients"] == ["help@example.com"]

    # an omitted password keeps the stored one
    again = client.put("/api/settings/mail", json={"from_name": "Slipwright Support"})
    assert again.json()["password_set"] is True
    assert again.json()["from_name"] == "Slipwright Support"

    cleared = client.put("/api/settings/mail", json={"clear_password": True})
    assert cleared.json()["password_set"] is False


def test_a_typo_in_the_sender_is_refused(client: TestClient, store: JobStore) -> None:
    _admin(client, store)
    bad = client.put("/api/settings/mail", json={"from_address": "no-reply at example.com"})
    assert bad.status_code == 400 and "not an email address" in bad.json()["detail"]
    bad_base = client.put("/api/settings/mail", json={"base_url": "example.com"})
    assert bad_base.status_code == 400


def test_the_test_message_goes_to_the_outbox_before_smtp_is_set_up(
    client: TestClient, store: JobStore
) -> None:
    _admin(client, store)
    sent = client.post("/api/settings/mail/test", json={"to": "ada@example.com", "lang": "en"})
    assert sent.status_code == 200, sent.text
    assert sent.json() == {"sent_to": "ada@example.com", "transport": "outbox"}
    letters = client.get("/api/settings/mail/outbox").json()
    assert letters[0]["to_address"] == "ada@example.com"
    assert "your email settings work" in letters[0]["subject"]


def test_with_no_support_address_the_page_names_the_admins(
    client: TestClient, store: JobStore
) -> None:
    _admin(client, store)
    shown = client.get("/api/settings/mail").json()
    assert shown["support_email"] == ""
    assert shown["support_recipients"] == ["ada@example.com"]
