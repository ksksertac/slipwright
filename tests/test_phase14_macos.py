"""T14.6: the one proof that needs a real Mac -- Xcode found, and a SwiftUI package built for
iOS by the worker, through the real API. Skipped anywhere Xcode is not; CI runs it on
macOS (the `macos` job in .github/workflows/docker.yml)."""

from __future__ import annotations

import io
import platform
import shutil
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright import worker_agent as agent
from slipwright.api import create_app
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

pytestmark = pytest.mark.skipif(
    platform.system() != "Darwin" or shutil.which("xcodebuild") is None,
    reason="needs macOS with Xcode",
)

PACKAGE = """// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Hello",
    platforms: [.iOS(.v16)],
    products: [.library(name: "Hello", targets: ["Hello"])],
    targets: [.target(name: "Hello")]
)
"""

VIEW = """import SwiftUI

public struct HelloView: View {
    public init() {}
    public var body: some View { Text("Hello from a Slipwright worker") }
}
"""

BUILD = (
    "xcodebuild -scheme Hello -destination 'generic/platform=iOS Simulator' "
    "-derivedDataPath .derived CODE_SIGNING_ALLOWED=NO build"
)


@pytest.fixture
def client(store: JobStore, worktrees_root: Path, seed: Profile) -> Iterator[TestClient]:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _tar(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_this_mac_says_it_builds_ios() -> None:
    assert "ios" in agent.detect().capabilities


def test_a_swiftui_package_is_built_for_ios_through_the_api(client: TestClient) -> None:
    code = client.post("/api/workers/code", json={"address": "http://192.168.1.20:8500"}).json()
    worker = agent.Worker(agent.pair(code["code"], name="ci mac", client=client), client=client)
    assert "ios" in worker.found.capabilities

    engine = client.app.state.engine  # type: ignore[attr-defined]
    task_id = engine.store.enqueue_worker_task(
        None,
        "job-1",
        "ios",
        [("ios build", BUILD), ("ios test", "true")],
        900,
        _tar({"Package.swift": PACKAGE, "Sources/Hello/HelloView.swift": VIEW}),
    )
    assert worker.once(wait_s=0) is True

    row = engine.store.worker_task_row(task_id)
    assert row is not None and row["state"] == "done"
    assert row["exit_code"] == 0, row["output"][-3000:]
    assert "BUILD SUCCEEDED" in row["output"]
