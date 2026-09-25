"""T11 — every account brings its own keys, and spends only its own.

This is the load-bearing test of the hosted model. If it ever goes red, one person is
paying for another person's work.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.store.scoped import ScopedStore, is_personal
from slipwright.store.settings import INSTALLATION
from slipwright.workspace import PortAllocator, Workspace


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8900, end=8999)),
        seed_profile=seed,
    )


@pytest.fixture
def app(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=True)) as c:
        yield c


def _person(app: TestClient, email: str) -> TestClient:
    person = TestClient(app.app, base_url=str(app.base_url))
    person.post("/api/auth/signup", json={"email": email, "password": "correct horse"})
    store: JobStore = app.app.state.engine.store  # type: ignore[attr-defined]
    user = store.find_by_email(email)
    assert user is not None
    store.mark_email_verified(user.id)
    return person


# --- what is personal and what is the server's -------------------------------------------


def test_the_split_between_personal_and_installation_settings() -> None:
    for name in (
        "providers.default",
        "providers.anthropic.api_key",
        "agents.backend",
        "sources.github.token",
        "jira",
        "jira.token",
    ):
        assert is_personal(name), f"{name} is somebody's own"
    for name in ("mail", "mail.password", "prices.last_fetch", "notifications.webhook_url",
                 "standards"):
        assert not is_personal(name), f"{name} belongs to the server"


def test_a_scoped_store_keeps_two_accounts_apart(store: JobStore) -> None:
    ada = ScopedStore(store, "ada")
    bob = ScopedStore(store, "bob")
    ada.set_setting("providers.anthropic.api_key", "sk-ada", secret=True)
    bob.set_setting("providers.anthropic.api_key", "sk-bob", secret=True)

    assert ada.get_setting("providers.anthropic.api_key") == "sk-ada"
    assert bob.get_setting("providers.anthropic.api_key") == "sk-bob"
    # and the installation has none of its own
    assert store.get_setting("providers.anthropic.api_key") is None

    # a server setting is the same one whoever writes it
    ada.set_setting("notifications.webhook_url", "https://hooks.example/ada")
    assert bob.get_setting("notifications.webhook_url") == "https://hooks.example/ada"
    assert store.get_setting("notifications.webhook_url", user_id=INSTALLATION)


# --- through the engine ---------------------------------------------------------------------


def test_each_account_routes_to_its_own_vendor(engine: Engine) -> None:
    ada = engine.for_user("ada")
    bob = engine.for_user("bob")
    ada.update_provider_settings("anthropic", api_key="sk-ada", make_default=True)
    bob.update_provider_settings("openai", api_key="sk-bob", make_default=True)

    assert ada.default_provider_name() == "anthropic"
    assert bob.default_provider_name() == "openai"

    ada_key = ada.provider_credentials("anthropic")
    assert ada_key is not None and ada_key.api_key == "sk-ada"
    assert bob.provider_credentials("anthropic") is None, "bob has no anthropic key"


def test_each_account_pins_its_own_agents(engine: Engine) -> None:
    from slipwright.schemas.profile import RoleName

    ada = engine.for_user("ada")
    bob = engine.for_user("bob")
    ada.update_provider_settings("anthropic", api_key="sk-ada")
    bob.update_provider_settings("anthropic", api_key="sk-bob")

    ada.assign_agent(RoleName.BACKEND, "anthropic", "ada-model")
    assert ada.agent_routing(RoleName.BACKEND) == ("anthropic", "ada-model")
    assert bob.agent_routing(RoleName.BACKEND) is None


def test_a_job_is_run_on_its_owners_keys(engine: Engine, repo: Path) -> None:
    """The point of the whole phase: the router a job runs through is the owner's."""
    from slipwright.schemas.project import Project

    engine.for_user("ada").update_provider_settings(
        "anthropic", api_key="sk-ada", make_default=True
    )
    project = engine.store.create_project(Project(name="ada's", repo_path=repo, owner_id="ada"))
    job = engine.create_job("x", project_id=project.id)
    assert job.owner_id == "ada"

    router = engine.provider_for(job.owner_id)
    assert router is not engine.provider_for("bob")
    # the engine bound to the job's owner resolves the owner's key
    creds = engine.for_user(job.owner_id).provider_credentials("anthropic")
    assert creds is not None and creds.api_key == "sk-ada"


# --- over HTTP -------------------------------------------------------------------------------


def test_the_settings_pages_are_personal(app: TestClient, repo: Path) -> None:
    ada = _person(app, "ada@example.com")
    bob = _person(app, "bob@example.com")

    saved = ada.put(
        "/api/settings/providers/anthropic",
        json={"api_key": "sk-ada-1234", "make_default": True},
    )
    assert saved.status_code == 200, saved.text

    def anthropic(person: TestClient) -> dict[str, object]:
        rows = person.get("/api/settings/providers").json()
        return next(r for r in rows if r["name"] == "anthropic")

    mine = anthropic(ada)
    assert mine["key_set"] is True
    assert mine["key_hint"] == "…1234"
    # the key itself is never handed back, to anybody
    assert "sk-ada-1234" not in ada.get("/api/settings/providers").text

    assert anthropic(bob)["key_set"] is False, "bob must not inherit ada's key"
    assert bob.get("/api/settings/jira").json()["site_url"] is None
