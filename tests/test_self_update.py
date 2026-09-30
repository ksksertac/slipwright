"""Installing a newer release from the version corner.

What is pinned down: a release is offered only when it is newer and only when it is a
release; the container is made again with everything that was kept outside it -- above
all a volume nobody named; a new version that never comes up puts the old one back; and
the button is anybody's, but can only ever install the release that was offered.
"""

from __future__ import annotations

import socket
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.update import (
    DockerError,
    Updater,
    backup_sqlite,
    helper_body,
    latest_release,
    recreated,
    replace,
)
from tests.pipeline import full_engine, full_provider

IMAGE = "ghcr.io/acme/slipwright"
OLD_ID = "a" * 64
IMAGE_ENV = ["PATH=/opt/venv/bin:/usr/bin", "SLIPWRIGHT_STATE_DIR=/data"]


def _registry(tags: list[str]) -> httpx.Client:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "anon"})
        assert request.headers["Authorization"] == "Bearer anon"
        return httpx.Response(200, json={"name": "acme/slipwright", "tags": tags})

    return httpx.Client(transport=httpx.MockTransport(answer))


def _old_container(**over: Any) -> dict[str, Any]:
    container: dict[str, Any] = {
        "Id": OLD_ID,
        "Name": "/slipwright",
        "Image": "sha256:old",
        "Config": {
            "Image": f"{IMAGE}:0.1.0",
            "Hostname": OLD_ID[:12],
            "Env": [*IMAGE_ENV, "ANTHROPIC_API_KEY=sk-mine"],
            "Labels": {"org.opencontainers.image.version": "0.1.0"},
            "Cmd": ["serve"],
            "User": "1000:1000",
            "ExposedPorts": {"8500/tcp": {}},
        },
        "HostConfig": {
            "Binds": ["slipwright-work:/work", "C:\\Users\\me\\repos:/repos:ro"],
            "PortBindings": {"8500/tcp": [{"HostPort": "8500"}]},
            "RestartPolicy": {"Name": "unless-stopped"},
        },
        "Mounts": [
            # /data was never named: `docker run` without -v gave it an anonymous volume
            {"Type": "volume", "Name": "f00dcafe", "Destination": "/data"},
            {"Type": "volume", "Name": "slipwright-work", "Destination": "/work"},
            {"Type": "bind", "Source": "C:\\Users\\me\\repos", "Destination": "/repos"},
        ],
        "NetworkSettings": {
            "Networks": {
                "bridge": {"Aliases": None, "IPAddress": "172.17.0.2"},
                "backend": {"Aliases": [OLD_ID[:12], "api"], "EndpointID": "e1"},
            }
        },
        "State": {"Running": True, "Health": {"Status": "healthy"}},
    }
    container.update(over)
    return container


OLD_IMAGE = {
    "Id": "sha256:old",
    "Config": {
        "Env": IMAGE_ENV,
        "Labels": {"org.opencontainers.image.version": "0.1.0"},
        "Cmd": ["serve"],
        "User": "1000:1000",
    },
}
NEW_IMAGE = {"Id": "sha256:new", "Config": {"Env": IMAGE_ENV, "Cmd": ["serve"]}}


class FakeDocker:
    """A daemon kept in a dictionary, answering the calls an update makes."""

    def __init__(self, *, new_health: str = "healthy") -> None:
        self.containers: dict[str, dict[str, Any]] = {OLD_ID: _old_container()}
        self.images = {"sha256:old": OLD_IMAGE, f"{IMAGE}:0.2.0": NEW_IMAGE}
        self.new_health = new_health
        self.calls: list[tuple[Any, ...]] = []
        self.created: dict[str, dict[str, Any]] = {}

    def _find(self, ref: str) -> dict[str, Any]:
        # a real daemon knows a container by its short id, which Docker makes the
        # hostname; here the test machine's hostname stands in for it
        if ref == socket.gethostname():
            ref = OLD_ID
        for cid, c in self.containers.items():
            if ref in (cid, cid[:12], str(c["Name"]).lstrip("/")):
                return c
        raise DockerError(f"no such container: {ref}")

    def container(self, ref: str) -> dict[str, Any]:
        return self._find(ref)

    def image(self, ref: str) -> dict[str, Any]:
        if ref not in self.images:
            raise DockerError(f"No such image: {ref}")
        return self.images[ref]

    def pull(self, repo: str, tag: str) -> None:
        self.calls.append(("pull", f"{repo}:{tag}"))

    def tag(self, image: str, repo: str, tag: str) -> None:
        self.calls.append(("tag", image, f"{repo}:{tag}"))

    def create(self, body: dict[str, Any], name: str) -> str:
        cid = f"new-{len(self.created)}"
        self.created[name] = body
        self.containers[cid] = {
            "Id": cid,
            "Name": f"/{name}",
            "State": {"Running": True, "Health": {"Status": self.new_health}},
        }
        self.calls.append(("create", name))
        return cid

    def connect(self, network: str, container: str, endpoint: dict[str, Any]) -> None:
        self.calls.append(("connect", network))

    def start(self, ref: str) -> None:
        self._find(ref)["State"]["Running"] = True
        self.calls.append(("start", str(self._find(ref)["Name"]).lstrip("/")))

    def stop(self, ref: str, timeout_s: int) -> None:
        self._find(ref)["State"]["Running"] = False
        self.calls.append(("stop", ref))

    def rename(self, ref: str, name: str) -> None:
        self._find(ref)["Name"] = f"/{name}"
        self.calls.append(("rename", name))

    def remove(self, ref: str, *, force: bool = False) -> None:
        target = self._find(ref)
        del self.containers[target["Id"]]
        self.calls.append(("remove", str(target["Name"]).lstrip("/")))

    def logs(self, ref: str, tail: int) -> str:
        return "migrating\nupdate failed: the new container did not come up"


# -- what is on offer ------------------------------------------------------------------


def test_the_newest_release_tag_is_the_one_offered() -> None:
    tags = ["latest", "sha-8b16ffa", "0.2.0", "0.10.1", "0.10", "0.9.3"]
    assert latest_release(IMAGE, _registry(tags)) == "0.10.1"


def test_builds_of_main_are_not_releases() -> None:
    assert latest_release(IMAGE, _registry(["latest", "sha-8b16ffa", "1.2"])) is None


def test_only_a_newer_release_is_offered() -> None:
    updater = Updater(image=IMAGE, current="0.2.0", registry=lambda _: "0.2.0")
    assert updater.check() is None
    updater.registry = lambda _: "0.3.0"
    assert updater.check() == "0.3.0"
    updater.registry = lambda _: "0.1.9"
    assert updater.check() is None


def test_a_registry_that_cannot_be_reached_offers_nothing_and_breaks_nothing() -> None:
    def down(_: str) -> str | None:
        raise httpx.ConnectError("no route to host")

    updater = Updater(image=IMAGE, current="0.1.0", registry=down)
    assert updater.check() is None
    assert updater.status().latest is None


def test_an_installation_can_turn_the_check_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLIPWRIGHT_UPDATE_IMAGE", "off")
    updater = Updater.from_env()
    updater.registry = lambda _: pytest.fail("the registry was asked")  # type: ignore[assignment]
    assert updater.check() is None


# -- making the container again --------------------------------------------------------


def test_a_volume_nobody_named_is_carried_over_by_name() -> None:
    body = recreated(_old_container(), OLD_IMAGE, NEW_IMAGE, f"{IMAGE}:0.2.0")
    mounts = body["HostConfig"]["Mounts"]
    assert {"Type": "volume", "Source": "f00dcafe", "Target": "/data"} in mounts
    # the named ones travel as they were declared, not twice
    assert body["HostConfig"]["Binds"] == _old_container()["HostConfig"]["Binds"]
    assert all(m["Target"] not in ("/work", "/repos") for m in mounts)


def test_the_persons_environment_is_kept_and_the_old_images_is_not() -> None:
    body = recreated(_old_container(), OLD_IMAGE, NEW_IMAGE, f"{IMAGE}:0.2.0")
    assert body["Env"] == ["ANTHROPIC_API_KEY=sk-mine"]
    # nor its labels, its command or its user: the new image brings its own
    assert body["Labels"] == {}
    assert "Cmd" not in body and "User" not in body


def test_without_the_old_image_the_new_one_decides_what_was_its_own() -> None:
    """Moving a tag deletes the image it moved from, under containerd's image store,
    while the container on it keeps running."""
    old = _old_container()
    old["Config"]["Env"] = ["PATH=/old/bin", "SLIPWRIGHT_STATE_DIR=/data", "FOO=bar"]
    old["Config"]["Labels"] = {"org.opencontainers.image.revision": "abc", "team": "infra"}
    body = recreated(old, None, NEW_IMAGE, f"{IMAGE}:0.2.0")
    assert body["Env"] == ["FOO=bar"]
    assert body["Labels"] == {"team": "infra"}
    assert "Cmd" not in body


def test_an_old_image_that_is_gone_does_not_stop_the_update() -> None:
    docker = FakeDocker()
    del docker.images["sha256:old"]
    replace(docker, OLD_ID, f"{IMAGE}:0.2.0", say=lambda _: None, poll_s=0)
    assert docker.created["slipwright"]["Env"] == ["ANTHROPIC_API_KEY=sk-mine"]


def test_ports_restart_policy_and_networks_are_kept_but_not_the_old_identity() -> None:
    body = recreated(_old_container(), OLD_IMAGE, NEW_IMAGE, f"{IMAGE}:0.2.0")
    assert body["HostConfig"]["PortBindings"] == {"8500/tcp": [{"HostPort": "8500"}]}
    assert body["HostConfig"]["RestartPolicy"] == {"Name": "unless-stopped"}
    assert "Hostname" not in body
    endpoints = body["NetworkingConfig"]["EndpointsConfig"]
    assert endpoints["backend"] == {"Aliases": ["api"]}
    assert endpoints["bridge"] == {}


def test_a_healthy_new_version_replaces_the_old_under_the_same_name() -> None:
    docker = FakeDocker()
    replace(docker, OLD_ID, f"{IMAGE}:0.2.0", say=lambda _: None, poll_s=0)
    names = {str(c["Name"]).lstrip("/") for c in docker.containers.values()}
    assert names == {"slipwright"}
    assert docker.created["slipwright"]["Image"] == f"{IMAGE}:0.2.0"
    # the old one is stopped before the new one starts: they share the database
    order = [c[0] for c in docker.calls]
    assert order.index("stop") < order.index("start")
    assert ("connect", "backend") in docker.calls


def test_a_new_version_that_never_comes_up_puts_the_old_one_back() -> None:
    docker = FakeDocker(new_health="unhealthy")
    with pytest.raises(DockerError):
        replace(
            docker, OLD_ID, f"{IMAGE}:0.2.0", say=lambda _: None, poll_s=0, health_timeout_s=0
        )
    assert list(docker.containers) == [OLD_ID]
    old = docker.containers[OLD_ID]
    assert old["Name"] == "/slipwright"
    assert old["State"]["Running"] is True


def test_a_compose_service_keeps_agreeing_with_what_runs() -> None:
    docker = FakeDocker()
    labels = {"com.docker.compose.project": "slipwright", "com.docker.compose.image": "x"}
    docker.containers[OLD_ID]["Config"]["Labels"] = labels
    docker.containers[OLD_ID]["Config"]["Image"] = f"{IMAGE}:latest"
    replace(docker, OLD_ID, f"{IMAGE}:0.2.0", say=lambda _: None, poll_s=0)
    # the name compose knows the service by now points at the release...
    assert ("tag", "sha256:new", f"{IMAGE}:latest") in docker.calls
    body = docker.created["slipwright"]
    assert body["Image"] == f"{IMAGE}:latest"
    # ...and the container says it runs that image, so `compose up` leaves it alone
    assert body["Labels"]["com.docker.compose.image"] == "sha256:new"


# -- the server's half -----------------------------------------------------------------


def test_the_database_is_copied_before_a_new_version_migrates_it(tmp_path: Path) -> None:
    db = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (42)")
    for _ in range(5):
        copy = backup_sqlite(db, "0.1.0", keep=3)
    with sqlite3.connect(copy) as conn:
        assert conn.execute("SELECT x FROM t").fetchone() == (42,)
    assert len(list((tmp_path / "backups").iterdir())) <= 3


def test_the_helper_gets_the_socket_and_nothing_else() -> None:
    me = _old_container()
    me["Mounts"].append(
        {"Type": "bind", "Source": "/run/docker.sock", "Destination": "/var/run/docker.sock"}
    )
    me["HostConfig"]["GroupAdd"] = ["999"]
    body = helper_body(me, f"{IMAGE}:0.2.0", "/var/run/docker.sock")
    assert body["HostConfig"]["Binds"] == ["/run/docker.sock:/var/run/docker.sock"]
    assert body["HostConfig"]["GroupAdd"] == ["999"]
    assert body["Image"] == f"{IMAGE}:0.2.0"
    assert body["Cmd"] == ["self-update", "--container", OLD_ID, "--image", f"{IMAGE}:0.2.0"]


def _updater(docker: FakeDocker | None, tmp_path: Path) -> Updater:
    socket_file = tmp_path / "docker.sock"
    socket_file.touch()
    updater = Updater(
        image=IMAGE,
        current="0.1.0",
        socket_path=str(socket_file) if docker else str(tmp_path / "absent.sock"),
        in_container=True,
        registry=lambda _: "0.2.0",
        docker_factory=lambda _: docker,  # type: ignore[arg-type,return-value]
    )
    updater.check()
    return updater


def test_a_helper_that_failed_says_why_once_the_old_version_is_back(tmp_path: Path) -> None:
    docker = FakeDocker()
    docker.containers["h"] = {
        "Id": "h",
        "Name": "/slipwright-update",
        "State": {"Running": False, "ExitCode": 1},
    }
    updater = _updater(docker, tmp_path)
    updater.reconcile(poll_s=0)
    assert updater.state == "failed"
    assert updater.error == "update failed: the new container did not come up"
    assert "h" not in docker.containers


def test_a_helper_still_at_work_is_waited_for(tmp_path: Path) -> None:
    """It starts this server and finishes only once it is healthy, so at startup it is
    always still running; looked at once, it would never be cleared away."""
    docker = FakeDocker()
    helper = {"Id": "h", "Name": "/slipwright-update", "State": {"Running": True}}
    docker.containers["h"] = helper
    looks = 0
    real = docker.container

    def container(ref: str) -> dict[str, Any]:
        nonlocal looks
        if ref == "slipwright-update":
            looks += 1
            if looks == 3:
                helper["State"] = {"Running": False, "ExitCode": 0}
        return real(ref)

    docker.container = container  # type: ignore[method-assign]
    updater = _updater(docker, tmp_path)
    updater.reconcile(poll_s=0)
    assert updater.state == "idle"
    assert "h" not in docker.containers


# -- the button ------------------------------------------------------------------------


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed))


def _client(engine: Engine, updater: Updater) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, updater=updater)) as c:
        yield c


def _accounts(store: JobStore) -> None:
    store.create_user("root", "pw0", is_admin=True)
    store.create_user("bob", "pw1", is_admin=False, email="bob@example.com")


def _sign_in(client: TestClient, store: JobStore) -> None:
    """Somebody who is not the administrator: the button is not the admin's alone."""
    if store.find_user("bob") is None:
        _accounts(store)
    resp = client.post("/api/auth/login", json={"username": "bob", "password": "pw1"})
    assert resp.status_code == 200, resp.text


def test_anybody_signed_in_is_told_a_new_version_is_out(
    engine: Engine, store: JobStore, tmp_path: Path
) -> None:
    for client in _client(engine, _updater(FakeDocker(), tmp_path)):
        _accounts(store)
        assert client.get("/api/update").status_code == 401
        _sign_in(client, store)
        status = client.get("/api/update").json()
        assert status["current"] == "0.1.0"
        assert status["latest"] == "0.2.0"
        assert status["can_install"] is True
        assert status["notes_url"] == "https://github.com/acme/slipwright/releases/tag/v0.2.0"


def test_a_press_pulls_the_release_and_hands_over_to_the_helper(
    engine: Engine, store: JobStore, tmp_path: Path
) -> None:
    docker = FakeDocker()
    for client in _client(engine, _updater(docker, tmp_path)):
        _sign_in(client, store)
        resp = client.post("/api/update", json={"version": "0.2.0"})
        assert resp.status_code == 202, resp.text
        updater: Updater = client.app.state.updater  # type: ignore[attr-defined]
        for _ in range(200):
            if updater.state != "pulling":
                break
            time.sleep(0.01)
        assert updater.state == "restarting", updater.error
    assert ("pull", f"{IMAGE}:0.2.0") in docker.calls
    assert docker.created["slipwright-update"]["Image"] == f"{IMAGE}:0.2.0"
    assert ("start", "slipwright-update") in docker.calls


def test_only_the_release_on_offer_can_be_installed(
    engine: Engine, store: JobStore, tmp_path: Path
) -> None:
    docker = FakeDocker()
    for client in _client(engine, _updater(docker, tmp_path)):
        _sign_in(client, store)
        resp = client.post("/api/update", json={"version": "6.6.6"})
        assert resp.status_code == 409
    assert docker.calls == []


def test_without_docker_the_button_says_what_to_run_instead(
    engine: Engine, store: JobStore, tmp_path: Path
) -> None:
    for client in _client(engine, _updater(None, tmp_path)):
        _sign_in(client, store)
        status = client.get("/api/update").json()
        assert status["latest"] == "0.2.0"
        assert status["can_install"] is False
        assert status["blocked"] == "no_docker"
        assert f"{IMAGE}:0.2.0" in status["command"]
        assert client.post("/api/update", json={"version": "0.2.0"}).status_code == 409
