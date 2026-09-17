from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OPENAPI = ROOT / "schemas" / "openapi.json"
CLIENT = WEB / "src" / "api" / "schema.d.ts"

# --- T8.1 React app skeleton --------------------------------------------------------------


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed))


def test_web_scaffold_is_wired_for_the_python_package() -> None:
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    for script in ("dev", "build", "lint", "typecheck", "gen:api", "check:api", "format:check"):
        assert script in package["scripts"], script
    for dep in ("react", "react-dom", "react-router-dom", "@tanstack/react-query"):
        assert dep in package["dependencies"], dep
    for dep in ("vite", "typescript", "eslint", "prettier", "openapi-typescript"):
        assert dep in package["devDependencies"], dep
    vite = (WEB / "vite.config.ts").read_text(encoding="utf-8")
    assert "slipwright/api/static" in vite  # build lands inside the package
    assert '"/api"' in vite and "8500" in vite  # dev proxy to the Python server
    tsconfig = json.loads((WEB / "tsconfig.app.json").read_text(encoding="utf-8"))
    assert tsconfig["compilerOptions"]["strict"] is True
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "slipwright/api/static/" in gitignore and "web/node_modules/" in gitignore


def test_generated_api_client_matches_the_committed_openapi() -> None:
    """The header of schema.d.ts names the OpenAPI file it was generated from."""
    assert CLIENT.is_file(), "web/src/api/schema.d.ts is missing; run `npm run gen:api` in web/"
    head = CLIENT.read_text(encoding="utf-8")[:400]
    match = re.search(r"openapi-sha256: ([0-9a-f]{64})", head)
    assert match, "schema.d.ts has no openapi-sha256 header; regenerate with `npm run gen:api`"
    current = hashlib.sha256(OPENAPI.read_bytes()).hexdigest()
    assert match.group(1) == current, (
        "web/src/api/schema.d.ts is stale; run `npm run gen:api` in web/ "
        "(after `uv run python scripts/export_schema.py`)"
    )


def test_spa_is_served_with_fallback(engine: Engine, tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Slipwright</title>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (static / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    app = create_app(engine, resume_on_startup=False, require_auth=False, static_dir=static)
    with TestClient(app) as client:
        assert "<title>Slipwright</title>" in client.get("/").text
        assert "<title>Slipwright</title>" in client.get("/projects/abc/board").text  # fallback
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/favicon.svg").text == "<svg/>"
        assert client.get("/api/nope").status_code == 404  # never falls back to the shell
        assert client.get("/api/projects").status_code == 200
        assert client.get("/legacy").status_code == 200  # old dashboard still reachable
        assert client.get("/../secret.txt").status_code in (200, 404)  # no traversal


def test_shell_is_public_but_api_is_not(engine: Engine, tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    engine.store.create_user("ada", "pw")
    app = create_app(engine, resume_on_startup=False, static_dir=static)  # auth on
    with TestClient(app) as client:
        assert client.get("/").status_code == 200  # the app shows its own login page
        assert client.get("/projects").status_code == 200
        assert client.get("/api/projects").status_code == 401
        assert client.get("/legacy").status_code == 401
        assert client.get("/healthz").status_code == 200


def test_without_a_build_the_root_explains_how_to_build(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, resume_on_startup=False, require_auth=False, static_dir=tmp_path)
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 503
        assert "npm run build" in resp.text
        assert client.get("/api/projects").status_code == 200
