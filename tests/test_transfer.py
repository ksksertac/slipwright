"""Moving an account to another Slipwright on the network: one code, everything goes, the
people stay, and a transfer that fails anywhere leaves both machines as they were."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.secrets import generate_key
from slipwright.store import JobStore
from slipwright.transfer import channel, incoming, nearby
from tests.pipeline import full_engine, full_provider

#: Where the receiving app answers inside the test process.
THERE = "http://testserver"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@dataclass
class Machine:
    engine: Engine
    client: TestClient
    root: Path

    @property
    def store(self) -> JobStore:
        return self.engine.raw_store


def _machine(root: Path, store: JobStore, seed: Profile, *, auth: bool = False) -> Machine:
    engine = full_engine(store, root / "worktrees", seed, full_provider(seed))
    client = TestClient(create_app(engine, resume_on_startup=False, require_auth=auth))
    return Machine(engine, client, root)


@pytest.fixture
def here(tmp_path: Path, seed: Profile) -> Iterator[Machine]:
    """The sending machine: its own database, and its own key."""
    root = tmp_path / "here"
    root.mkdir()
    with JobStore(root / "jobs.sqlite3", secret_key=generate_key()) as store:
        machine = _machine(root, store, seed)
        with machine.client:
            yield machine


@pytest.fixture
def there(tmp_path: Path, store: JobStore, seed: Profile) -> Iterator[Machine]:
    """The receiving machine, on the suite's store -- PostgreSQL when the suite runs on it."""
    root = tmp_path / "there"
    root.mkdir()
    machine = _machine(root, store, seed)
    with machine.client:
        yield machine


@pytest.fixture
def linked(here: Machine, there: Machine) -> tuple[Machine, Machine]:
    """The sender's server calls the receiver's app in this process."""
    here.client.app.state.transfer_client = there.client  # type: ignore[attr-defined]
    return here, there


def _code(machine: Machine) -> str:
    got = machine.client.post("/api/transfer/code")
    assert got.status_code == 200, got.text
    return str(got.json()["code"])


def _send(here: Machine, code: str, **extra: Any) -> dict[str, Any]:
    started = here.client.post("/api/transfer/send", json={"address": THERE, "code": code, **extra})
    assert started.status_code == 202, started.text
    sending_id = started.json()["id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status: dict[str, Any] = here.client.get(f"/api/transfer/send/{sending_id}").json()
        if status["state"] in ("done", "failed"):
            return status
        time.sleep(0.05)
    raise AssertionError("the transfer never ended")


def _project(machine: Machine, repo: Path, name: str = "shop") -> Project:
    return machine.engine.create_project(Project(name=name, repo_path=repo))


def _at_a_gate_with_work(machine: Machine, project: Project) -> Job:
    """A development stopped at a gate, its worktree holding work not yet committed."""
    job = machine.engine.create_job("add a basket", project_id=project.id)
    job = machine.engine.start(job.id)
    assert job.state in APPROVAL_STATES, job.state
    job = machine.engine._ensure_workspace(job)
    assert job.worktree_path is not None
    (job.worktree_path / "basket.py").write_bytes(b"BASKET = []\n")
    return job


# -- the whole of it --------------------------------------------------------------------


def test_an_account_moves_whole_and_carries_on_there(
    linked: tuple[Machine, Machine], repo: Path
) -> None:
    here, there = linked
    project = _project(here, repo)
    _git(repo, "checkout", "-q", "-b", "feature/unpushed")
    (repo / "notes.md").write_bytes(b"committed on a branch nobody pushed\n")
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-q", "-m", "notes")
    _git(repo, "checkout", "-q", "main")
    (repo / "draft.txt").write_bytes(b"not committed yet\n")
    job = _at_a_gate_with_work(here, project)
    here.store.add_attachment(
        project_id=project.id,
        owner_id=None,
        name="spec.pdf",
        media_type="application/pdf",
        data=b"%PDF-1.4 the requirements",
        text="the requirements",
        pages=1,
        scope="project",
    )
    here.store.set_setting("sources.github.token", "ghp_secret", secret=True)
    here.store.set_setting("mail", {"host": "smtp.example.com"})

    status = _send(here, _code(there))

    assert status["state"] == "done", status["error"]
    assert status["moved"] == ["shop"]
    moved = there.store.get_project(project.id)
    assert moved.name == "shop"
    assert moved.repo_path is not None and moved.repo_path.parent == there.engine.repos_root
    # the checkout is the repository itself: the unpushed branch and the draft are there
    assert "feature/unpushed" in _git(moved.repo_path, "branch", "--list")
    assert (moved.repo_path / "draft.txt").read_bytes() == b"not committed yet\n"
    # the development is at the same gate, its uncommitted work in a worktree of its own
    arrived = there.store.get(job.id)
    assert arrived.state is job.state
    assert len(arrived.history) == len(here.store.get(job.id).history)
    assert arrived.worktree_path is not None
    assert arrived.worktree_path.parent == there.engine.workspace.worktrees_root
    assert (arrived.worktree_path / "basket.py").read_bytes() == b"BASKET = []\n"
    # a secret sealed with the sender's key opens with the receiver's
    assert there.store.get_setting("sources.github.token") == "ghp_secret"
    assert there.store.get_setting("mail") == {"host": "smtp.example.com"}
    assert [a.name for a in there.store.list_attachments(project.id)] == ["spec.pdf"]
    # and nothing was taken from the sender
    assert here.store.get_project(project.id).name == "shop"
    # the gate is answered there and the development carries on
    carried = there.engine.approve(job.id)
    assert carried.state is not job.state


def test_the_receiving_screen_follows_the_transfer(
    linked: tuple[Machine, Machine], repo: Path
) -> None:
    here, there = linked
    _project(here, repo)
    assert there.client.get("/api/transfer/incoming").status_code == 204
    _send(here, _code(there))
    arrived = there.client.get("/api/transfer/incoming").json()
    assert arrived["state"] == "done"
    assert arrived["moved"] == ["shop"]
    assert all(step["state"] == "done" for step in arrived["steps"])


def test_moved_again_a_project_is_not_doubled(linked: tuple[Machine, Machine], repo: Path) -> None:
    here, there = linked
    _project(here, repo)
    assert _send(here, _code(there))["state"] == "done"
    again = _send(here, _code(there))
    assert again["state"] == "done"
    assert again["moved"] == [] and again["skipped"] == 1
    assert len(there.store.list_projects()) == 1


def test_deleting_after_removes_it_here_once_it_is_there(
    linked: tuple[Machine, Machine], repo: Path
) -> None:
    here, there = linked
    project = _project(here, repo)
    status = _send(here, _code(there), delete_after=True)
    assert status["state"] == "done", status["error"]
    assert [p.id for p in there.store.list_projects()] == [project.id]
    assert here.store.list_projects() == []
    assert repo.is_dir()  # a folder the person pointed at is theirs, whatever happens


# -- what does not move -----------------------------------------------------------------


def test_people_stay_and_the_work_belongs_to_whoever_showed_the_code(
    tmp_path: Path, store: JobStore, seed: Profile, repo: Path
) -> None:
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    with JobStore(root_a / "jobs.sqlite3", secret_key=generate_key()) as store_a:
        alice = store_a.create_user("alice", "correct horse battery", email="alice@a.example")
        bob = store.create_user("bob", "correct horse battery", email="bob@b.example")
        here = _machine(root_a, store_a, seed, auth=True)
        there = _machine(root_b, store, seed, auth=True)
        with here.client, there.client:
            here.client.app.state.transfer_client = there.client  # type: ignore[attr-defined]
            for machine, who in ((here, "alice"), (there, "bob")):
                login = machine.client.post(
                    "/api/auth/login", json={"username": who, "password": "correct horse battery"}
                )
                assert login.status_code == 200, login.text
            project = here.engine.create_project(
                Project(name="shop", repo_path=repo, owner_id=alice.id)
            )
            store_a.set_setting("sources.github.token", "ghp_alice", secret=True, user_id=alice.id)

            status = _send(here, _code(there))

            assert status["state"] == "done", status["error"]
            assert [u.username for u in store.list_users()] == ["bob"]
            assert store.get_project(project.id).owner_id == bob.id
            assert store.get_setting("sources.github.token", user_id=bob.id) == "ghp_alice"
            shown = there.client.get("/api/projects").json()
            assert [p["name"] for p in shown] == ["shop"]


def test_settings_of_this_machine_stay_on_it(linked: tuple[Machine, Machine], repo: Path) -> None:
    here, there = linked
    _project(here, repo)
    here.store.set_setting("workers.address", "http://192.168.1.20:8500")
    assert _send(here, _code(there))["state"] == "done"
    assert there.store.get_setting("workers.address") is None


# -- what is refused --------------------------------------------------------------------


def _wrong(code: str) -> str:
    """The same slot, another secret: a code typed with one character wrong."""
    slot, secret = channel.parse_code(code)
    other = ("Z" if secret[0] != "Z" else "Y") + secret[1:]
    body = slot + other
    text = body + channel._check(body)
    return "SW-" + "-".join(text[i : i + 4] for i in range(0, len(text), 4))


def test_a_wrong_code_moves_nothing_and_is_spent(
    linked: tuple[Machine, Machine], repo: Path
) -> None:
    here, there = linked
    _project(here, repo)
    code = _code(there)
    failed = _send(here, _wrong(code))
    assert failed["state"] == "failed"
    assert "did not match" in failed["error"]
    assert there.store.list_projects() == []
    # the right code was spent by the wrong guess: there is only ever one try
    assert "used or has run out" in _send(here, code)["error"]


def test_a_code_past_its_time_opens_nothing(linked: tuple[Machine, Machine], repo: Path) -> None:
    here, there = linked
    _project(here, repo)
    code = _code(there)
    desk: incoming.Desk = there.client.app.state.transfer_desk  # type: ignore[attr-defined]
    for offer in desk._offers.values():
        offer.made -= incoming.SHOWN_S + incoming.GRACE_S + 1
    failed = _send(here, code)
    assert failed["state"] == "failed"
    assert "run out" in failed["error"]


def test_the_code_before_still_works_while_it_is_typed(
    linked: tuple[Machine, Machine], repo: Path
) -> None:
    here, there = linked
    _project(here, repo)
    first = _code(there)
    _code(there)  # the screen has moved on to the next one
    assert _send(here, first)["state"] == "done"


def test_a_running_development_holds_the_move(linked: tuple[Machine, Machine], repo: Path) -> None:
    here, there = linked
    project = _project(here, repo)
    job = here.engine.create_job("add a basket", project_id=project.id)
    here.store.update_state(job.id, JobState.BACKLOG, note="running")
    refused = here.client.post("/api/transfer/send", json={"address": THERE, "code": _code(there)})
    assert refused.status_code == 409
    assert "running" in refused.json()["detail"]


def test_different_versions_do_not_move(there: Machine) -> None:
    code = _code(there)
    slot, secret = channel.parse_code(code)
    handshake = channel.SenderHandshake(secret)
    import base64

    got = there.client.post(
        "/api/transfer/peer/pair",
        json={
            "slot": slot,
            "message": base64.b64encode(handshake.start()).decode(),
            "revision": "0001_older",
            "version": "0.1.0",
        },
    )
    assert got.status_code == 409
    assert "update the older one" in got.json()["detail"]


def test_a_part_without_the_key_ends_the_transfer(there: Machine) -> None:
    import base64

    from slipwright.store.migrate import current_revision

    slot, secret = channel.parse_code(_code(there))
    handshake = channel.SenderHandshake(secret)
    paired = there.client.post(
        "/api/transfer/peer/pair",
        json={
            "slot": slot,
            "message": base64.b64encode(handshake.start()).decode(),
            "revision": current_revision(there.store.db),
        },
    ).json()
    forged = channel.seal(b"k" * 32, paired["session"], 0, channel.Part({"kind": "manifest"}))
    got = there.client.post(f"/api/transfer/peer/{paired['session']}/part", content=forged)
    assert got.status_code == 409
    key = handshake.finish(base64.b64decode(paired["message"]), paired["confirm"])
    honest = channel.seal(key, paired["session"], 0, channel.Part({"kind": "manifest"}))
    again = there.client.post(f"/api/transfer/peer/{paired['session']}/part", content=honest)
    assert again.status_code == 409  # one forged part and the transfer is over


def test_a_failed_write_leaves_no_checkout_behind(
    linked: tuple[Machine, Machine], repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here, there = linked
    project = _project(here, repo)
    _at_a_gate_with_work(here, project)

    def broken(*_a: Any, **_k: Any) -> dict[str, int]:
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(incoming, "_write", broken)
    failed = _send(here, _code(there))
    assert failed["state"] == "failed"
    assert "the disk is full" in failed["error"]
    assert there.store.list_projects() == []
    for left in (there.engine.repos_root, there.engine.workspace.worktrees_root):
        assert not left.exists() or not any(left.iterdir())
    assert here.store.get_project(project.id).name == "shop"


def test_transfers_off_shuts_every_door(there: Machine) -> None:
    there.engine.transfer_enabled = False
    assert there.client.get("/api/transfer").json()["enabled"] is False
    assert there.client.post("/api/transfer/code").status_code == 404
    assert there.client.get("/api/transfer/peer/hello").status_code == 404


def test_off_by_default_on_a_hosted_installation() -> None:
    from slipwright.transfer import enabled_by_default

    assert enabled_by_default(None, {}) is True
    assert enabled_by_default("postgresql+psycopg://x/y", {}) is False
    assert enabled_by_default("postgresql+psycopg://x/y", {"SLIPWRIGHT_TRANSFER": "on"}) is True
    assert enabled_by_default(None, {"SLIPWRIGHT_TRANSFER": "off"}) is False


# -- the code ---------------------------------------------------------------------------


def test_a_code_is_forgiving_to_read_and_strict_to_spend() -> None:
    code, slot, secret = channel.new_code()
    assert code.startswith("SW-") and len(code.replace("-", "")) == 14
    assert channel.parse_code(code.lower().replace("-", " ")) == (slot, secret)
    assert channel.parse_code(code.replace("0", "O").replace("1", "I")) == (slot, secret)
    typo = code[:-2] + ("A" if code[-2] != "A" else "B") + code[-1]
    with pytest.raises(channel.CodeError):
        channel.parse_code(typo)


def test_a_wrong_code_gives_a_different_key() -> None:
    sender = channel.SenderHandshake("AAAAAAAA")
    answer, key = channel.receive_handshake("BBBBBBBB", sender.start())
    with pytest.raises(channel.ChannelError):
        sender.finish(answer, channel.confirmation(key))


# -- finding the others -----------------------------------------------------------------


def test_the_page_says_which_network_to_look_at() -> None:
    networks, ports = nearby.targets("http://192.168.1.11:8600", None, own="10.0.0.5")
    assert networks == ["192.168.1.0/24", "10.0.0.0/24"]
    assert ports == {8500, 8600}
    # nothing to go on -- localhost, in Docker -- and the usual home networks are tried
    networks, _ = nearby.targets("http://localhost:8500", own=None)
    assert networks == list(nearby.USUAL_NETWORKS)


def test_a_container_does_not_offer_its_bridge_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nearby, "in_container", lambda: True)
    assert nearby.own_address() is None


def test_looking_around_finds_the_others_and_not_itself() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "192.168.1.30":
            return httpx.Response(200, json={"app": "slipwright", "instance": "me", "name": "me"})
        if host == "192.168.1.40":
            return httpx.Response(200, text="<html>a printer</html>")
        return httpx.Response(
            200, json={"app": "slipwright", "instance": "laptop", "name": "LAPTOP-OFIS"}
        )

    found = nearby.look(
        "http://192.168.1.30:8500",
        instance="me",
        client=httpx.Client(transport=httpx.MockTransport(answer)),
        own=lambda: None,
        scan=lambda nets, ports, skip: [
            "http://192.168.1.30:8500",
            "http://192.168.1.40:8500",
            "http://192.168.1.24:8500",
            "http://192.168.1.24:8600",  # the same machine by another door
        ],
    )
    assert [(p["name"], p["address"]) for p in found] == [
        ("LAPTOP-OFIS", "http://192.168.1.24:8500")
    ]


def test_this_machine_tells_its_card(here: Machine, repo: Path) -> None:
    _project(here, repo)
    card = here.client.get("/api/transfer", params={"address": "http://192.168.1.11:8500"}).json()
    assert card["enabled"] is True
    assert card["projects"] == 1
    assert "http://192.168.1.11:8500" in card["addresses"]
    hello = here.client.get("/api/transfer/peer/hello").json()
    assert hello["instance"] == card["instance"]


def test_a_part_too_large_is_refused_unread(there: Machine) -> None:
    import base64

    from slipwright.store.migrate import current_revision

    slot, secret = channel.parse_code(_code(there))
    paired = there.client.post(
        "/api/transfer/peer/pair",
        json={
            "slot": slot,
            "message": base64.b64encode(channel.SenderHandshake(secret).start()).decode(),
            "revision": current_revision(there.store.db),
        },
    ).json()
    got = there.client.post(
        f"/api/transfer/peer/{paired['session']}/part", content=b"x" * (incoming.MAX_PART + 1)
    )
    assert got.status_code == 413
