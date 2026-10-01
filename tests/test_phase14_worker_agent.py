"""T14.4: `slipwright worker` on the Mac -- pairs, says what it can build, builds in a
directory of its own with nothing of the Mac's environment but what is named, and stops
when the server no longer knows it."""

from __future__ import annotations

import io
import os
import stat
import sys
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright import worker_agent as agent
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workers import CodeError
from tests.pipeline import full_engine, full_provider

LAN = "http://192.168.1.20:8500"
PY = sys.executable


@pytest.fixture
def client(store: JobStore, worktrees_root: Path, seed: Profile) -> Iterator[TestClient]:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _store(client: TestClient) -> JobStore:
    engine: Engine = client.app.state.engine  # type: ignore[attr-defined]
    return engine.store  # type: ignore[return-value]


def _tar(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _paired(client: TestClient, capabilities: list[str]) -> agent.Worker:
    code = client.post("/api/workers/code", json={"address": LAN}).json()["code"]
    config = agent.pair(code, name="test mac", client=client)
    assert config["address"] == LAN and config["token"].startswith("swk_")
    return agent.Worker(config, client=client, found=agent.Found(capabilities=capabilities))


# -- what it can build -----------------------------------------------------------------------


def _fake_xcodebuild(root: Path) -> str:
    bin_dir = root / "bin"
    bin_dir.mkdir()
    tool = bin_dir / ("xcodebuild.bat" if os.name == "nt" else "xcodebuild")
    tool.write_text("@echo off\n" if os.name == "nt" else "#!/bin/sh\n")
    tool.chmod(0o755)
    return str(bin_dir)


def test_ios_needs_a_real_xcode_not_the_command_line_tools_stub(tmp_path: Path) -> None:
    env = {"PATH": _fake_xcodebuild(tmp_path), "PATHEXT": ".BAT"}
    found = agent.detect(env, system="Darwin", home=tmp_path, run=lambda argv: 0)
    assert "ios" in found.capabilities
    stub = agent.detect(env, system="Darwin", home=tmp_path, run=lambda argv: 1)
    assert "ios" not in stub.capabilities
    assert any("Xcode" in m for m in stub.missing)
    assert (
        "ios" not in agent.detect(env, system="Linux", home=tmp_path, run=lambda a: 0).capabilities
    )


def test_android_studios_sdk_is_found_where_it_keeps_it(tmp_path: Path) -> None:
    (tmp_path / "Library" / "Android" / "sdk" / "platforms" / "android-35").mkdir(parents=True)
    jdk = tmp_path / "jdk"
    jdk.mkdir()
    found = agent.detect(
        {"PATH": "", "JAVA_HOME": str(jdk)}, system="Darwin", home=tmp_path, run=lambda a: 1
    )
    assert "android" in found.capabilities
    assert found.env == {
        "ANDROID_HOME": str(tmp_path / "Library" / "Android" / "sdk"),
        "JAVA_HOME": str(jdk),
    }
    bare = agent.detect({"PATH": ""}, system="Darwin", home=tmp_path / "nobody", run=lambda a: 1)
    assert bare.capabilities == [] and any("Android Studio" in m for m in bare.missing)


# -- pairing -------------------------------------------------------------------------------


def test_the_pairing_is_kept_for_this_user_alone(tmp_path: Path) -> None:
    path = agent.save_config(
        {"address": LAN, "token": "swk_x", "worker_id": "w"}, tmp_path / "w.json"
    )
    assert agent.load_config(path) == {"address": LAN, "token": "swk_x", "worker_id": "w"}
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert agent.load_config(tmp_path / "missing.json") is None


def test_a_bad_copy_of_the_code_never_reaches_the_network() -> None:
    class Unreachable:
        def post(self, *a: object, **k: object) -> None:
            raise AssertionError("the network was touched")

    with pytest.raises(CodeError):
        agent.pair("SW-0000-0000", client=Unreachable())  # type: ignore[arg-type]


class OnlyAt:
    """The network as the Mac sees it: the server answers at one address only."""

    def __init__(self, client: TestClient, where: str) -> None:
        self.client, self.where = client, where
        self.tried: list[str] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.tried.append(url)
        if not url.startswith(self.where):
            raise httpx.ConnectError("nobody there")
        return self.client.post(url.removeprefix(self.where), **kwargs)


def test_a_code_made_at_localhost_finds_the_server_on_the_macs_network(
    client: TestClient,
) -> None:
    code = client.post("/api/workers/code", json={"address": "http://localhost:8500"})
    net = OnlyAt(client, "http://192.168.1.30:8500")
    config = agent.pair(
        code.json()["code"],
        name="test mac",
        client=net,  # type: ignore[arg-type]
        look_around=lambda port: ["192.168.1.7", "192.168.1.30"],
    )
    # this Mac first (the server in Docker beside it), then its network, in order
    assert [u.removesuffix("/api/worker/pair") for u in net.tried] == [
        "http://localhost:8500",
        "http://192.168.1.7:8500",
        "http://192.168.1.30:8500",
    ]
    assert config["address"] == "http://192.168.1.30:8500"


def test_the_network_is_searched_only_when_nothing_nearer_answered(client: TestClient) -> None:
    code = client.post("/api/workers/code", json={"address": LAN}).json()["code"]

    def never(port: int) -> list[str]:
        raise AssertionError("the network was searched")

    config = agent.pair(
        code,
        client=OnlyAt(client, LAN),
        look_around=never,  # type: ignore[arg-type]
    )
    assert config["address"] == LAN


def test_a_server_nowhere_near_is_said_plainly(client: TestClient) -> None:
    code = client.post("/api/workers/code", json={"address": "http://localhost:8500"})
    with pytest.raises(agent.Unpaired, match="same network"):
        agent.pair(
            code.json()["code"],
            client=OnlyAt(client, "http://10.9.9.9:1"),  # type: ignore[arg-type]
            look_around=lambda port: [],
        )


# -- building --------------------------------------------------------------------------------


def test_a_build_runs_in_a_fresh_directory_and_reports_like_the_gate(client: TestClient) -> None:
    worker = _paired(client, ["ios"])
    check = f'"{PY}" -c "import pathlib; print(pathlib.Path(\'App/main.swift\').read_text())"'
    task_id = _store(client).enqueue_worker_task(
        None,
        "job-1",
        "ios",
        [("ios build", check), ("ios test", f'"{PY}" -c "raise SystemExit(3)"'), ("never", "x")],
        60,
        _tar({"App/main.swift": "print(1)"}),
    )
    assert worker.once(wait_s=0) is True

    row = _store(client).worker_task_row(task_id)
    assert row is not None and row["state"] == "done"
    assert row["exit_code"] == 3  # the first command that failed, and nothing after it
    assert "print(1)" in row["output"] and "[ios build: exit 0]" in row["output"]
    assert "[ios test: exit 3]" in row["output"] and "never" not in row["output"]
    assert worker.once(wait_s=0) is False  # nothing more to do


def test_a_build_sees_only_the_named_environment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIPWRIGHT_SECRET_KEY", "never-in-a-build")
    worker = _paired(client, ["ios"])
    dump = f'"{PY}" -c "import os; print(sorted(os.environ.items()))"'
    task_id = _store(client).enqueue_worker_task(
        None, "job-1", "ios", [("ios build", dump)], 60, _tar({"a": "b"})
    )
    worker.once(wait_s=0)
    row = _store(client).worker_task_row(task_id)
    assert row is not None and row["exit_code"] == 0
    assert "never-in-a-build" not in row["output"]


def test_an_archive_cannot_write_outside_its_directory(client: TestClient, tmp_path: Path) -> None:
    worker = _paired(client, ["ios"])
    task_id = _store(client).enqueue_worker_task(
        None, "job-1", "ios", [("ios build", "echo hi")], 60, _tar({"../escaped.txt": "x"})
    )
    with pytest.raises(tarfile.TarError):
        worker.once(wait_s=0)
    assert not (Path(os.environ.get("TMP", "/tmp")) / "escaped.txt").exists()
    row = _store(client).worker_task_row(task_id)
    assert row is not None and row["state"] == "running"  # never reported as built


def test_a_removed_mac_stops_rather_than_polling_forever(client: TestClient) -> None:
    worker = _paired(client, ["ios"])
    worker_id = client.get("/api/workers").json()[0]["id"]
    client.delete(f"/api/workers/{worker_id}")
    with pytest.raises(agent.Unpaired, match="pair it again"):
        worker.once(wait_s=0)


def test_the_login_service_restarts_it_and_keeps_a_log(tmp_path: Path) -> None:
    path, text = agent.launch_agent(["/opt/homebrew/bin/slipwright", "worker"], home=tmp_path)
    assert path == tmp_path / "Library" / "LaunchAgents" / "com.slipwright.worker.plist"
    assert "<string>/opt/homebrew/bin/slipwright</string>" in text
    assert "<key>KeepAlive</key>\n  <true/>" in text and "<key>RunAtLoad</key>" in text
    assert "slipwright-worker.log" in text


def test_the_command_says_whether_it_is_paired_and_what_it_can_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from slipwright.cli import main

    monkeypatch.setattr(agent, "config_path", lambda home=None: tmp_path / "worker.json")
    monkeypatch.setattr(agent, "detect", lambda *a, **k: agent.Found(missing=["iOS: no Xcode"]))
    assert main(["worker", "status"]) == 0
    said = capsys.readouterr().out
    assert "not paired" in said and "can build: nothing" in said and "iOS: no Xcode" in said

    assert main(["worker"]) == 1  # nothing to run without a pairing
    assert "--connect" in capsys.readouterr().err
