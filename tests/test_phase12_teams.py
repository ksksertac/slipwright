"""T12 — the people an account puts on its agents.

One administrator owns everything. A team is built one agent at a time: an address is
invited onto the Architect, answers the letter, and from then on sees the owner's projects
and approves at the Architect's gates and nowhere else. Leaving, being taken off and
declining are the same row ending, and the last one out is signed out of the application.

Everything here runs against the outbox transport, so the invitation link is read straight
out of the database, exactly as the identity tests read the verification one.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.api.auth import SIGNED_OUT_HEADER, SIGNED_OUT_REMOVED
from slipwright.auth import UserStatus
from slipwright.engine import Engine
from slipwright.mail import read_outbox
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from slipwright.teams import agent_for_gate
from slipwright.workspace import PortAllocator, Workspace
from tests.pipeline import full_engine, full_provider

BASE = "https://slipwright.example"
OWNER = {"email": "owner@acme.com", "password": "correct horse", "name": "Ada"}
MEMBER = "ksksertac@gmail.com"


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    eng = Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8900, end=8999)),
        seed_profile=seed,
    )
    eng.update_mail_settings(base_url=BASE)
    return eng


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=True)) as c:
        yield c


def _other(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=True)) as c:
        yield c


@pytest.fixture
def member_client(engine: Engine) -> Iterator[TestClient]:
    """A second browser: the invited person, who is not the owner."""
    yield from _other(engine)


def _token(store: JobStore, to: str) -> str:
    letters = read_outbox(store, to=to)
    assert letters, f"no letter was written to {to}"
    for word in letters[0]["body"].split():
        if word.startswith(BASE):
            return parse_qs(urlparse(word).query)["token"][0]
    raise AssertionError(f"no link in the letter to {to}")


def _sign_up_owner(client: TestClient, store: JobStore) -> dict[str, str]:
    created = client.post("/api/auth/signup", json=OWNER)
    assert created.status_code == 201, created.text
    user = store.find_by_email(OWNER["email"])
    assert user is not None
    store.mark_email_verified(user.id)
    return created.json()  # type: ignore[no-any-return]


def _invite(client: TestClient, role: str = "architect", email: str = MEMBER) -> dict[str, object]:
    sent = client.post(f"/api/agents/{role}/members", json={"email": email, "lang": "en"})
    assert sent.status_code == 201, sent.text
    return sent.json()  # type: ignore[no-any-return]


def _accept(client: TestClient, store: JobStore, email: str = MEMBER) -> dict[str, object]:
    taken = client.post(
        "/api/auth/accept-invitation",
        json={"token": _token(store, email), "password": "my own password", "name": "Sertaç"},
    )
    assert taken.status_code == 200, taken.text
    return taken.json()  # type: ignore[no-any-return]


# --- the invitation ---------------------------------------------------------------------


def test_an_invitation_takes_the_address_names_the_agent_and_starts_no_session(
    client: TestClient, member_client: TestClient, store: JobStore
) -> None:
    _sign_up_owner(client, store)
    membership = _invite(client)
    assert membership["status"] == "invited"
    assert membership["role"] == "architect"

    # the account exists from the moment the letter goes out, and cannot be logged into
    invited = store.find_by_email(MEMBER)
    assert invited is not None and invited.status is UserStatus.INVITED
    assert invited.owner_id == store.find_by_email(OWNER["email"]).id  # type: ignore[union-attr]

    # ...and the address is no longer free: this is the company-mail rule
    taken = member_client.post(
        "/api/auth/signup", json={"email": MEMBER.upper(), "password": "another password"}
    )
    assert taken.status_code == 409

    token = _token(store, MEMBER)
    opened = member_client.post("/api/auth/invitation", json={"token": token})
    assert opened.status_code == 200, opened.text
    assert opened.json()["agents"] == ["architect"]
    assert opened.json()["inviter"] == "Ada"
    # reading it does not spend it, and it has started no session
    assert member_client.post("/api/auth/invitation", json={"token": token}).status_code == 200
    assert member_client.get("/api/auth/me").status_code == 401

    accepted = _accept(member_client, store)
    assert accepted["username"] == "Sertaç"
    assert accepted["email_verified_at"] is not None
    assert member_client.get("/api/auth/me").json()["email"] == MEMBER
    # the link is spent
    assert (
        member_client.post("/api/auth/invitation", json={"token": token}).status_code == 400
    )


def test_somebody_put_on_several_agents_answers_one_invitation(
    client: TestClient, member_client: TestClient, store: JobStore
) -> None:
    """Three agents is still one person being asked one question.

    A letter each would make them answer it three times and leave the other links spent
    for nothing, so the memberships are made together and the invitation names them all.
    """
    _sign_up_owner(client, store)
    sent = client.post(
        "/api/team/members",
        json={"email": MEMBER, "lang": "en", "roles": ["architect", "designer", "qa"]},
    )
    assert sent.status_code == 201, sent.text
    assert [m["role"] for m in sent.json()] == ["architect", "designer", "qa"]
    assert {m["status"] for m in sent.json()} == {"invited"}

    # one link, and it opens onto every agent they were asked for
    opened = member_client.post("/api/auth/invitation", json={"token": _token(store, MEMBER)})
    assert opened.status_code == 200, opened.text
    assert sorted(opened.json()["agents"]) == ["architect", "designer", "qa"]

    # the cards say who holds them, which is what the list is for
    holders = {a["role"]: a["holders"] for a in client.get("/api/agents").json()}
    assert holders["architect"] and holders["designer"] and holders["qa"]
    assert holders["backend"] == []

    # asking again for agents they already hold is refused, and says which
    again = client.post(
        "/api/team/members", json={"email": MEMBER, "lang": "en", "roles": ["architect"]}
    )
    assert again.status_code == 409
    assert "Architect" in again.json()["detail"]

    # ...but an agent they are not on yet is simply added
    more = client.post(
        "/api/team/members", json={"email": MEMBER, "lang": "en", "roles": ["architect", "backend"]}
    )
    assert more.status_code == 201, more.text
    assert [m["role"] for m in more.json()] == ["backend"]


def test_declining_ends_the_invitation_and_keeps_the_address(
    client: TestClient, member_client: TestClient, store: JobStore
) -> None:
    _sign_up_owner(client, store)
    _invite(client)
    token = _token(store, MEMBER)
    said_no = member_client.post("/api/auth/decline-invitation", json={"token": token})
    assert said_no.status_code == 204

    team = client.get("/api/agents/architect/members").json()
    assert [m["status"] for m in team] == ["declined"]
    # no session was started, the account cannot be logged into, and the address stays taken
    assert member_client.get("/api/auth/me").status_code == 401
    assert store.find_by_email(MEMBER).status is UserStatus.REMOVED  # type: ignore[union-attr]
    again = member_client.post(
        "/api/auth/signup", json={"email": MEMBER, "password": "another password"}
    )
    assert again.status_code == 409
    # and the owner can simply invite again
    assert _invite(client)["status"] == "invited"


def test_one_address_is_invited_once_and_never_out_of_another_account(
    client: TestClient, store: JobStore, engine: Engine
) -> None:
    _sign_up_owner(client, store)
    _invite(client)
    twice = client.post("/api/agents/architect/members", json={"email": MEMBER})
    assert twice.status_code == 409
    # the same person may hold a second agent
    assert _invite(client, role="qa")["role"] == "qa"

    # somebody else's account is never quietly pulled onto a team
    store.create_user("Bob", "bob's password", email="bob@other.com", verified=True)
    refused = client.post("/api/agents/qa/members", json={"email": "bob@other.com"})
    assert refused.status_code == 409


# --- what a member may do ---------------------------------------------------------------


@pytest.fixture
def team(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> Iterator[tuple[TestClient, TestClient, str]]:
    """An owner whose development waits at the Architect's gate, and a member on it.

    The first gate of a development is the Architect's: the backlog and the plan are
    approved together (``plan_gate == "combined"``), so the Product Owner's own gate is
    not visited at all.
    """
    provider = full_provider(seed, phases=1)
    eng = full_engine(store, worktrees_root, seed, provider)
    eng.update_mail_settings(base_url=BASE)
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as owner, TestClient(app) as member:
        _sign_up_owner(owner, store)
        made = owner.post("/api/projects", json={"name": "demo", "repo_path": str(repo)})
        assert made.status_code == 201, made.text
        project_id = made.json()["id"]
        started = owner.post(f"/api/projects/{project_id}/jobs", json={"request": "a health check"})
        assert started.status_code == 201, started.text
        job_id = started.json()["id"]  # the API ran it to its first gate on the way out
        _invite(owner, role="architect")
        _accept(member, store)
        yield owner, member, job_id


def test_a_member_sees_the_owners_work_and_approves_only_at_their_own_gate(
    team: tuple[TestClient, TestClient, str], store: JobStore
) -> None:
    owner, member, job_id = team
    job = owner.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == JobState.AWAITING_ARCHITECTURE_APPROVAL.value
    assert agent_for_gate(JobState.AWAITING_ARCHITECTURE_APPROVAL) is RoleName.ARCHITECT

    # the member sees the owner's project and development, not an empty installation
    assert [p["name"] for p in member.get("/api/projects").json()] == ["demo"]
    assert member.get(f"/api/jobs/{job_id}").status_code == 200
    assert member.get("/api/me/team").json()["agents"] == ["architect"]

    # the plan is the Architect's, so the edit and the approval are both theirs
    edited = member.put(f"/api/jobs/{job_id}/plan", json={"phases": job["data"]["plan"]["phases"]})
    assert edited.status_code == 200, edited.text
    approved = member.post(f"/api/jobs/{job_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] != JobState.AWAITING_ARCHITECTURE_APPROVAL.value


def test_a_member_may_not_approve_another_agents_gate_or_start_anything(
    team: tuple[TestClient, TestClient, str], store: JobStore, repo: Path
) -> None:
    owner, member, job_id = team
    # carry it past the Architect's gate to QA's, which is not the member's
    assert owner.post(f"/api/jobs/{job_id}/approve").status_code == 200
    assert owner.get(f"/api/jobs/{job_id}").json()["state"] == JobState.AWAITING_TEST_APPROVAL.value

    refused = member.post(f"/api/jobs/{job_id}/approve")
    assert refused.status_code == 403
    assert "qa" in refused.json()["detail"]
    assert member.put(f"/api/jobs/{job_id}/tests", json={"test_cases": []}).status_code == 403
    assert member.post("/api/jobs/approve", json={"job_ids": [job_id]}).json()["approved"] == 0

    # nothing that starts or steers work is theirs either
    mine = member.post("/api/projects", json={"name": "mine", "repo_path": str(repo)})
    assert mine.status_code == 403
    assert member.post("/api/projects/x/jobs", json={"request": "hi"}).status_code == 403
    assert member.post(f"/api/jobs/{job_id}/retry").status_code == 403
    assert member.post(f"/api/jobs/{job_id}/message", json={"text": "hello"}).status_code == 403
    assert member.delete(f"/api/jobs/{job_id}").status_code == 403
    # and the settings are the owner's
    assert member.get("/api/users").status_code == 403
    assert member.get("/api/settings/mail").status_code == 403
    assert member.put("/api/settings/github", json={"owner": "acme"}).status_code == 403


def test_a_member_configures_their_own_agent_and_no_other(
    team: tuple[TestClient, TestClient, str],
) -> None:
    owner, member, _job_id = team
    mine = next(a for a in member.get("/api/agents").json() if a["role"] == "architect")
    assert mine["mine"] is True and mine["people"] == 1
    others = next(a for a in member.get("/api/agents").json() if a["role"] == "qa")
    assert others["mine"] is False

    # an unknown provider is a 400 either way: what matters is that the door opened
    assert member.put(
        "/api/agents/architect/routing", json={"provider": "nope", "model": "x"}
    ).status_code == 400
    assert member.put(
        "/api/agents/qa/routing", json={"provider": "nope", "model": "x"}
    ).status_code == 403


# --- leaving, being taken off, and the door ------------------------------------------------


def test_being_taken_off_the_last_agent_signs_the_person_out_with_a_reason(
    team: tuple[TestClient, TestClient, str], store: JobStore
) -> None:
    owner, member, _job_id = team
    membership = owner.get("/api/agents/architect/members").json()[0]
    assert membership["status"] == "active"

    ended = owner.delete(f"/api/agents/architect/members/{membership['id']}")
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "removed"

    # the browser that is open right now is told why, rather than simply forgetting
    bounced = member.get("/api/auth/me")
    assert bounced.status_code == 401
    assert bounced.headers[SIGNED_OUT_HEADER] == SIGNED_OUT_REMOVED
    assert "no longer on any agent" in bounced.json()["detail"]

    # and so is the login page, instead of "wrong password"
    refused = member.post(
        "/api/auth/login", json={"username": MEMBER, "password": "my own password"}
    )
    assert refused.status_code == 403
    assert refused.headers[SIGNED_OUT_HEADER] == SIGNED_OUT_REMOVED
    # they were told by letter as well
    assert any("architect" in m["subject"] for m in read_outbox(store, to=MEMBER))


def test_a_member_may_step_off_an_agent_themselves(
    team: tuple[TestClient, TestClient, str], store: JobStore
) -> None:
    owner, member, _job_id = team
    # somebody already on the team is handed the second agent rather than asked again
    assert _invite(owner, role="qa")["status"] == "active"

    first = owner.get("/api/agents/architect/members").json()[0]
    left = member.delete(f"/api/agents/architect/members/{first['id']}")
    assert left.status_code == 200
    assert left.json()["status"] == "left"
    # one agent is left, so they are still in and only QA's gates are theirs
    assert member.get("/api/me/team").json()["agents"] == ["qa"]
    assert member.get("/api/projects").status_code == 200

    qa = owner.get("/api/agents/qa/members").json()[0]
    assert member.delete(f"/api/agents/qa/members/{qa['id']}").status_code == 200
    assert member.get("/api/projects").status_code == 401
    assert store.find_by_email(MEMBER).status is UserStatus.REMOVED  # type: ignore[union-attr]

    # being invited back turns the account round again
    _invite(owner, role="qa")
    assert store.find_by_email(MEMBER).status is UserStatus.INVITED  # type: ignore[union-attr]


def test_a_member_cannot_take_anybody_else_off_an_agent(
    team: tuple[TestClient, TestClient, str], store: JobStore
) -> None:
    owner, member, _job_id = team
    _invite(owner, role="architect", email="second@acme.com")
    rows = owner.get("/api/agents/architect/members").json()
    other = next(m for m in rows if m["email"] == "second@acme.com")
    assert member.delete(f"/api/agents/architect/members/{other['id']}").status_code == 403
    assert owner.delete(f"/api/agents/architect/members/{other['id']}").status_code == 200


# --- being told ----------------------------------------------------------------------------


def test_the_people_on_an_agent_are_written_to_when_a_gate_becomes_theirs(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    eng = full_engine(store, worktrees_root, seed, provider)
    eng.update_mail_settings(base_url=BASE)
    app = create_app(eng, resume_on_startup=False, require_auth=True)
    with TestClient(app) as owner, TestClient(app) as member:
        _sign_up_owner(owner, store)
        _invite(owner, role="architect")
        _accept(member, store)
        before = len(read_outbox(store, to=MEMBER))
        made = owner.post("/api/projects", json={"name": "demo", "repo_path": str(repo)})
        job_id = owner.post(
            f"/api/projects/{made.json()['id']}/jobs", json={"request": "a health check"}
        ).json()["id"]
        assert eng.store.get(job_id).state is JobState.AWAITING_ARCHITECTURE_APPROVAL

        letters = read_outbox(store, to=MEMBER)
        assert len(letters) == before + 1
        assert "architecture" in letters[0]["body"]
        assert job_id in letters[0]["body"]
        assert "waiting for" in (eng.store.get(job_id).history[-1].note or "")

        # the same gate is never written about twice, however often the job is resumed
        eng.resume(job_id)
        assert len(read_outbox(store, to=MEMBER)) == before + 1

        # QA's gate is QA's: the Architect is not written to again
        owner.post(f"/api/jobs/{job_id}/approve")
        assert eng.store.get(job_id).state is JobState.AWAITING_TEST_APPROVAL
        assert len(read_outbox(store, to=MEMBER)) == before + 1

# --- the database that came before ------------------------------------------------------


def test_a_database_written_before_teams_upgrades_into_one(tmp_path: Path) -> None:
    """The old shape is built by taking the new one apart: drop what 0007 adds, stamp the
    revision before it, and let the store upgrade itself the way a server does on start."""
    from alembic import command
    from sqlalchemy import inspect, text

    from slipwright.store.db import Database
    from slipwright.store.migrate import _config, migrate
    from slipwright.store.schema import metadata

    db = Database(str(tmp_path / "old.sqlite3"))
    try:
        metadata.create_all(db.engine)
        with db.begin() as conn:
            conn.execute(text("DROP TABLE agent_members"))
            conn.execute(text("ALTER TABLE users DROP COLUMN owner_id"))
            conn.execute(
                text(
                    "INSERT INTO users (id, username, email, status, password_hash,"
                    " is_admin, created_at) VALUES ('u1', 'Ada', 'ada@acme.com', 'active',"
                    " 'x', 1, '2026-01-01T00:00:00+00:00')"
                )
            )
        command.stamp(_config(db), "0006_merge_support_and_standards")

        migrate(db)

        assert "agent_members" in set(inspect(db.engine).get_table_names())
        assert "owner_id" in {c["name"] for c in inspect(db.engine).get_columns("users")}
        with db.connect() as conn:
            rows = conn.execute(text("SELECT username, owner_id FROM users")).fetchall()
        # everybody who came before is their own account, and is left exactly as they were
        assert rows == [("Ada", None)]
    finally:
        db.dispose()
