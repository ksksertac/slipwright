"""Set up a recordable demo: a server with no API key, and a repository to start from.

The README wants half a minute of Slipwright used the way a person first uses it: look at
the agents, create a project, and watch the development stop at each gate for somebody to
approve it. The thing that makes that awkward to record is everything around it -- a key,
a repository with something in it, agents that say something worth reading. This does all
of it and leaves the server running on a throwaway state directory.

    uv run python scripts/demo.py

Nothing here talks to a model. Every role answers from a script, so the run is free,
offline and the same every time -- which is what you want when the take has to be
repeated. The script is the test suite's canned one with its words replaced: "scripted
backlog" is fine for an assertion and meaningless on camera, so for the demo each agent
says what a real one would say about the request below.

Pass ``--keep`` to leave the state directory behind, ``--port`` to move it, or ``--root``
to put it somewhere whose path you do not mind on screen.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent

#: The project the recording creates, and what it asks for first. Short enough to read in
#: a screen recording, and recognisably a real request rather than "test".
PROJECT = "health-service"
REQUEST = "Add a /health endpoint that reports the version"

#: The repository the project is created on: a small FastAPI service, so the brief the
#: agents write about it has something true to say.
SEED: dict[str, str] = {
    "README.md": "# health-service\n\nA small FastAPI service.\n",
    "pyproject.toml": (
        '[project]\nname = "health-service"\nversion = "1.4.0"\n'
        'dependencies = ["fastapi", "uvicorn"]\n\n'
        '[dependency-groups]\ndev = ["pytest", "httpx"]\n'
    ),
    "app/__init__.py": "",
    "app/main.py": (
        'from fastapi import FastAPI\n\napp = FastAPI(title="health-service")\n\n\n'
        '@app.get("/items")\ndef items() -> list[str]:\n    return []\n'
    ),
    "tests/test_items.py": (
        "from fastapi.testclient import TestClient\n\nfrom app.main import app\n\n\n"
        "def test_items_start_empty() -> None:\n"
        '    assert TestClient(app).get("/items").json() == []\n'
    ),
}

HEALTH = """\
from importlib.metadata import version

from fastapi import APIRouter

router = APIRouter()

# read once: the version of a running process does not change under it
VERSION = version("health-service")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}
"""

MAIN = """\
from fastapi import FastAPI

from app.health import router as health

app = FastAPI(title="health-service")
app.include_router(health)


@app.get("/items")
def items() -> list[str]:
    return []
"""

TESTS = """\
from importlib.metadata import version

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_answers_ok() -> None:
    assert client.get("/health").status_code == 200


def test_health_reports_the_installed_version() -> None:
    assert client.get("/health").json()["version"] == version("health-service")
"""


def a_repository(at: Path) -> Path:
    """A git repository with one commit in it: a development needs somewhere to branch."""
    repo = at / PROJECT
    for name, text in SEED.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    run = lambda *args: subprocess.run(  # noqa: E731 - a local shorthand, used three times
        ["git", *args], cwd=repo, check=True, capture_output=True
    )
    run("init", "-q", "-b", "main")
    run("add", "-A")
    run("-c", "user.name=demo", "-c", "user.email=demo@localhost", "commit", "-qm", "first commit")
    return repo


def the_script(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """What each agent says, as (replies by role, replies to the asides).

    Only the words differ from the canned script; the shapes are the same, so the pipeline
    walks exactly the path the test suite proves it walks.
    """
    backlog = {
        "summary": "One epic: the service can be asked whether it is up, and which build.",
        "breakdown": {
            "epics": [
                {
                    "id": "e1",
                    "title": "Service health",
                    "description": "Something a load balancer and a person can both ask.",
                    "stories": [
                        {
                            "id": "s1",
                            "title": "As an operator I can see that the service is up",
                            "tasks": [
                                {"id": "t1", "title": "GET /health answers 200 with status ok"},
                            ],
                        },
                        {
                            "id": "s2",
                            "title": "As an operator I can see which version is running",
                            "tasks": [
                                {"id": "t2", "title": "Report the installed package version"},
                            ],
                        },
                    ],
                }
            ]
        },
    }
    plan = {
        "summary": "A router of its own, the version read once at import.",
        "profile": profile,
        "decisions": [
            "/health lives in its own router, so no future auth dependency reaches it",
            "The version comes from the installed package, not a constant to keep in step",
            "No database call: it says the process is up, not that its dependencies are",
        ],
        "phases": [
            {
                "goal": "Health router answering status ok",
                "files": ["app/health.py"],
                "task_id": "t1",
                "domain": "backend",
            },
            {
                "goal": "Version from package metadata, router mounted",
                "files": ["app/health.py", "app/main.py"],
                "task_id": "t2",
                "domain": "backend",
            },
        ],
    }
    build = {
        "summary": "Added app/health.py and mounted it in app/main.py.",
        "phase_complete": True,
        "changes": [
            {"path": "app/health.py", "content": HEALTH},
            {"path": "app/main.py", "content": MAIN},
        ],
    }

    def qa(req: Any) -> dict[str, Any]:
        if '"stage": 1' in req.prompt:
            return {
                "summary": "Two cases: it answers, and it tells the truth about the version.",
                "test_cases": [
                    {
                        "name": "health answers ok",
                        "description": "GET /health returns 200 and status ok",
                    },
                    {
                        "name": "health reports the version",
                        "description": "the version matches the installed package",
                    },
                ],
            }
        return {
            "summary": "tests/test_health.py, both cases green.",
            "changes": [{"path": "tests/test_health.py", "content": TESTS}],
        }

    replies = {
        "po": backlog,
        "architect": plan,
        "backend": build,
        "web_ui": build,
        "mobile_ui": build,
        "qa": qa,
        "devops": {
            "summary": "Branch pushed, pull request opened.",
            "pr_title": "Add /health endpoint reporting the version",
            "pr_body": "GET /health answers `{status, version}`; the version is read from "
            "the installed package. Covered by tests/test_health.py.",
        },
        "supervisor": {
            "summary": "Covers the request and nothing beyond it.",
            "decision": "approve",
            "confidence": 0.92,
            "risk": "low",
            "reasons": ["Small, additive change", "Nothing existing is modified in behaviour"],
        },
    }
    asides = {
        "analysis": {
            "summary": "A small FastAPI service with pytest.",
            "items": [
                {
                    "category": "product",
                    "title": "A small HTTP service",
                    "detail": "Serves /items; no persistence yet.",
                },
                {
                    "category": "stack",
                    "title": "Python, FastAPI, uvicorn",
                    "detail": "Declared in pyproject.toml, version 1.4.0.",
                },
                {
                    "category": "modules",
                    "title": "app/main.py holds the application",
                    "detail": "Routes are declared on the app directly.",
                },
                {
                    "category": "testing",
                    "title": "pytest with FastAPI's TestClient",
                    "detail": "tests/ mirrors app/.",
                },
            ],
        },
    }
    return replies, asides


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8500)
    parser.add_argument("--keep", action="store_true", help="leave the state directory behind")
    parser.add_argument(
        "--root",
        type=Path,
        help="where to set it up (default: a temporary directory). The checkout's path is "
        "shown on screen, so a recording wants one that says nothing about the machine",
    )
    args = parser.parse_args()

    if args.root:
        if args.root.exists() and any(args.root.iterdir()):
            parser.error(f"{args.root} is not empty; the demo removes it afterwards")
        args.root.mkdir(parents=True, exist_ok=True)
        scratch = args.root.resolve()
    else:
        scratch = Path(tempfile.mkdtemp(prefix="slipwright-demo-"))
    repos = scratch / "repos"
    a_repository(repos)

    # The development has to get past the build gate, and the recording should not wait on
    # an install. The demo profile's two commands are therefore a command that succeeds --
    # the same trick the test suite uses, for the same reason.
    profile = json.loads((HERE / "examples" / "python-fastapi.profile.json").read_text("utf-8"))
    always = f'"{sys.executable}" -c "pass"'
    profile["build_cmd"], profile["test_cmd"] = always, always
    profile_path = scratch / "demo.profile.json"
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    env = {
        "SLIPWRIGHT_PROVIDER": "scripted",
        "SLIPWRIGHT_PROFILE": str(profile_path),
        "SLIPWRIGHT_STATE_DIR": str(scratch / "state"),
        "SLIPWRIGHT_WORK_DIR": str(scratch / "work"),
        # the folder the new-project form offers checkouts from: the recording picks one
        "SLIPWRIGHT_LOCAL_REPOS": str(repos),
        "SLIPWRIGHT_DEMO_PROJECT": "0",  # the worked example would crowd the recording
        "SLIPWRIGHT_PORT": str(args.port),
    }
    # the engine reads a few of these from the process rather than from Settings
    os.environ.update(env)

    import uvicorn

    from slipwright.api import create_app
    from slipwright.config import Settings, build_engine
    from slipwright.schemas.profile import RoleName

    settings = Settings.from_env({**os.environ})
    engine = build_engine(settings)
    # The canned script, reworded. It is the object every account's engine is handed
    # (`Engine.for_user` keeps an injected provider as it is), so changing it in place
    # changes it for whoever the recording is logged in as.
    script = engine.provider
    replies, asides = the_script(profile)
    for role, reply in replies.items():
        script.replies[RoleName(role)] = reply  # type: ignore[attr-defined]
    script.discovery.update(asides)  # type: ignore[attr-defined]

    print("\n  Demo set up. No API key is used; every role answers from the script.\n")
    print(f"  Open:  http://127.0.0.1:{args.port}/agents")
    print(f"  Then:  New project -> Local checkout -> {PROJECT}, and ask for")
    print(f'         "{REQUEST}"\n')
    # flushed, because uvicorn's own logging starts a line later and would bury the link
    print(
        "  Ctrl-C stops the server." + ("" if args.keep else f"  {scratch} is removed after.\n"),
        flush=True,
    )

    try:
        # a recording has nobody to log in: the state directory is a throwaway and the
        # server is bound to this machine
        app = create_app(engine, require_auth=False)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    except KeyboardInterrupt:  # pragma: no cover - the person stopped the recording
        pass
    finally:
        engine.store.close()
        if not args.keep:
            shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
