"""Set up a recordable demo: a server with no API key, and a repository to start from.

The README wants a minute of Slipwright used the way a person uses it: look at the agents,
create a project, and follow one development all the way -- the Designer's screens, the
gates somebody approves, a gate approved from Telegram, the tasks moving across the Jira
board, DevOps writing the AWS deployment and pushing the branch. The thing that makes
that awkward to record is everything around it -- a key, a repository, a bot, a Jira site,
a Git host, agents that say something worth reading. This does all of it and leaves the
server running on a throwaway state directory.

    uv run python scripts/demo.py

Nothing here talks to a model or to the internet. Every role answers from a script, and
Telegram, Jira and the Git host are stood in for by ``demo_world.py``, so the run is free,
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
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import demo_world

HERE = Path(__file__).resolve().parent.parent

#: The project the recording creates, and what it asks for first. Short enough to read in
#: a screen recording, and a request with screens in it: a backend-only change would skip
#: the Designer, and the Designer is half of what the take is for.
PROJECT = "notes-service"
REQUEST = "A page to write, search and tag notes"

#: The repository the project is created on: a small FastAPI service with an API and no
#: page, so the brief has something true to say and the request something to add.
SEED: dict[str, str] = {
    "README.md": "# notes-service\n\nNotes over HTTP. FastAPI, in memory for now.\n",
    "pyproject.toml": (
        '[project]\nname = "notes-service"\nversion = "0.3.0"\n'
        'dependencies = ["fastapi", "uvicorn"]\n\n'
        '[dependency-groups]\ndev = ["pytest", "httpx"]\n'
    ),
    "app/__init__.py": "",
    "app/main.py": (
        "from fastapi import FastAPI\n\nfrom app.store import NOTES\n\n"
        'app = FastAPI(title="notes-service")\n\n\n'
        '@app.get("/api/notes")\ndef notes() -> list[dict[str, object]]:\n    return NOTES\n'
    ),
    "app/store.py": "NOTES: list[dict[str, object]] = []\n",
    "tests/test_notes.py": (
        "from fastapi.testclient import TestClient\n\nfrom app.main import app\n\n\n"
        "def test_notes_start_empty() -> None:\n"
        '    assert TestClient(app).get("/api/notes").json() == []\n'
    ),
}

SEARCH = """\
from fastapi import APIRouter

from app.store import NOTES

router = APIRouter(prefix="/api/notes")


@router.get("")
def notes(q: str = "", tag: str = "") -> list[dict[str, object]]:
    # title and body, case-folded: people search for words, not for exact strings
    words = q.casefold().split()
    found = [
        n for n in NOTES
        if all(w in f"{n['title']} {n['body']}".casefold() for w in words)
        and (not tag or tag in n.get("tags", []))
    ]
    return sorted(found, key=lambda n: str(n["updated"]), reverse=True)
"""

LIST_PAGE = """\
<!doctype html>
<title>Notes</title>
<link rel="stylesheet" href="/static/notes.css">
<header><h1>Notes</h1><a class="primary" href="/edit">New note</a></header>
<input id="q" type="search" placeholder="Search notes" autofocus>
<nav id="tags"></nav>
<ul id="notes"></ul>
<p id="empty" hidden>No notes match. Try fewer words.</p>
<script src="/static/notes.js"></script>
"""

EDIT_PAGE = """\
<!doctype html>
<title>Edit note</title>
<link rel="stylesheet" href="/static/notes.css">
<form id="note">
  <input name="title" placeholder="Title" required>
  <textarea name="body" rows="12" placeholder="Write something"></textarea>
  <div id="tags" class="chips"><input placeholder="Add a tag and press Enter"></div>
  <footer><a href="/">Cancel</a><button class="primary">Save</button></footer>
</form>
<script src="/static/edit.js"></script>
"""

TESTS = """\
from fastapi.testclient import TestClient

from app.main import app
from app.store import NOTES

client = TestClient(app)


def setup_function() -> None:
    NOTES[:] = [
        {"title": "Standup", "body": "Ship search", "tags": ["work"], "updated": "2"},
        {"title": "Groceries", "body": "Milk, eggs", "tags": ["home"], "updated": "1"},
    ]


def test_search_finds_a_word_in_the_body() -> None:
    assert [n["title"] for n in client.get("/api/notes?q=search").json()] == ["Standup"]


def test_a_tag_narrows_the_list() -> None:
    assert [n["title"] for n in client.get("/api/notes?tag=home").json()] == ["Groceries"]


def test_the_notes_page_is_served() -> None:
    assert "Search notes" in client.get("/").text
"""

# -- the Designer's pictures ----------------------------------------------------------------
# Real screens, drawn the way the Designer is told to draw them: one self-contained
# document each, no script, no network, the words the screen will really show.

SCREENS = Path(__file__).resolve().parent / "demo-screens"
NOTES_WEB = (SCREENS / "notes-web.html").read_text(encoding="utf-8")
NOTES_MOBILE = (SCREENS / "notes-mobile.html").read_text(encoding="utf-8")
EDIT_WEB = (SCREENS / "edit-web.html").read_text(encoding="utf-8")


# -- DevOps: the deployment it proposes, and the files it writes ---------------------------

DEPLOY_FILES: dict[str, str] = {
    "deployment/Dockerfile": """\
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY web ./web
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
    "deployment/ecs-task-definition.json": json.dumps(
        {
            "family": "notes-service",
            "networkMode": "awsvpc",
            "requiresCompatibilities": ["FARGATE"],
            "cpu": "256",
            "memory": "512",
            "executionRoleArn": "${EXECUTION_ROLE_ARN}",
            "containerDefinitions": [
                {
                    "name": "notes-service",
                    "image": "${IMAGE}",
                    "portMappings": [{"containerPort": 8000}],
                    "healthCheck": {
                        "command": ["CMD-SHELL", "curl -f http://localhost:8000/api/notes"]
                    },
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": "/ecs/notes-service",
                            "awslogs-region": "${AWS_REGION}",
                            "awslogs-stream-prefix": "web",
                        },
                    },
                }
            ],
        },
        indent=2,
    )
    + "\n",
    "deployment/deploy.sh": """\
#!/usr/bin/env bash
# Build the image, push it to ECR and roll the ECS service onto it.
set -euo pipefail
: "${AWS_REGION:?}" "${AWS_ACCOUNT_ID:?}" "${ECS_CLUSTER:?}" "${EXECUTION_ROLE_ARN:?}"

REPO="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/notes-service"
IMAGE="$REPO:$(git rev-parse --short HEAD)"

aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "${REPO%/*}"
docker build -f deployment/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"

export IMAGE
envsubst < deployment/ecs-task-definition.json > /tmp/task.json
TASK=$(aws ecs register-task-definition --cli-input-json file:///tmp/task.json \\
  --query 'taskDefinition.taskDefinitionArn' --output text)
aws ecs update-service --cluster "$ECS_CLUSTER" --service notes-service \\
  --task-definition "$TASK"
aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services notes-service
""",
    ".github/workflows/deploy.yml": """\
name: deploy
on:
  push:
    branches: [main]
permissions:
  id-token: write
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE }}
          aws-region: ${{ vars.AWS_REGION }}
      - run: deployment/deploy.sh
        env:
          AWS_REGION: ${{ vars.AWS_REGION }}
          AWS_ACCOUNT_ID: ${{ vars.AWS_ACCOUNT_ID }}
          ECS_CLUSTER: ${{ vars.ECS_CLUSTER }}
          EXECUTION_ROLE_ARN: ${{ secrets.EXECUTION_ROLE_ARN }}
""",
}

DEPLOY_PLAN: dict[str, Any] = {
    "summary": "A container on ECS Fargate behind a load balancer, deployed on merge to main.",
    "target": "aws",
    "services": ["ECR", "ECS on Fargate", "Application Load Balancer", "CloudWatch Logs"],
    "scripts": [
        {"path": "deployment/Dockerfile", "purpose": "The service as one slim image"},
        {
            "path": "deployment/ecs-task-definition.json",
            "purpose": "Fargate task: 0.25 vCPU, 512 MB, health check, logs to CloudWatch",
        },
        {
            "path": "deployment/deploy.sh",
            "purpose": "Build, push to ECR, register the task, roll the service",
        },
        {
            "path": ".github/workflows/deploy.yml",
            "purpose": "Run deploy.sh on every merge to main, through an assumed role",
        },
    ],
    "notes": [
        "An AWS account and an IAM role GitHub Actions can assume (AWS_DEPLOY_ROLE)",
        "An ECS cluster and a service called notes-service behind the load balancer",
        "AWS_REGION, AWS_ACCOUNT_ID and ECS_CLUSTER as repository variables",
    ],
}


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


def a_remote(at: Path) -> Path:
    """The bare repository the branch is pushed into: GitHub, as far as the push knows."""
    remote = at / f"{PROJECT}.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True)
    return remote


def _context(req: Any) -> dict[str, Any]:
    """The context a role is handed, read as JSON rather than matched as text: how it is
    laid out is the engine's business (compact since T15.7)."""
    marker = "Context:\n"
    start = req.prompt.find(marker)
    if start < 0:
        return {}
    context, _ = json.JSONDecoder().raw_decode(req.prompt, start + len(marker))
    return context if isinstance(context, dict) else {}


def _phase_of(req: Any) -> int:
    """Which phase a specialist is being asked for, from the context it is handed."""
    return int((_context(req).get("current_phase") or {}).get("number", 1))


def the_script(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """What each agent says, as (replies by role, replies to the asides).

    Only the words differ from the canned script; the shapes are the same, so the pipeline
    walks exactly the path the test suite proves it walks.
    """
    backlog = {
        "summary": "One epic: notes you can find again. Search first, then the page, then tags.",
        "breakdown": {
            "epics": [
                {
                    "id": "e1",
                    "title": "Notes on the web",
                    "description": "Write a note, find it again, group it by tag.",
                    "stories": [
                        {
                            "id": "s1",
                            "title": "As a writer I can find a note by searching",
                            "tasks": [
                                {"id": "t1", "title": "Search notes by title, body and tag"},
                                {"id": "t2", "title": "Notes page with a search box"},
                            ],
                        },
                        {
                            "id": "s2",
                            "title": "As a writer I can write and tag a note",
                            "tasks": [
                                {"id": "t3", "title": "Editor page with tags"},
                            ],
                        },
                    ],
                }
            ]
        },
    }
    plan = {
        "summary": "Search in the API first, then the two pages on top of it.",
        "profile": profile,
        "decisions": [
            "Search is one query parameter on the existing list, not a second endpoint",
            "The pages are plain HTML served by FastAPI: no build step for two screens",
            "Tags live on the note; the tag list is derived, not a table of its own",
        ],
        "phases": [
            {
                "goal": "Search by words and tag",
                "files": ["app/notes.py", "app/main.py"],
                "task_id": "t1",
                "domain": "backend",
                "depends_on": [],
            },
            {
                "goal": "The notes page",
                "files": ["web/index.html", "web/notes.js"],
                "task_id": "t2",
                "domain": "web",
                # the two pages need the search, not each other: written side by side
                "depends_on": [1],
            },
            {
                "goal": "The editor, with tags",
                "files": ["web/edit.html", "web/edit.js"],
                "task_id": "t3",
                "domain": "web",
                "depends_on": [1],
            },
        ],
    }
    design = {
        "summary": "Two screens: the list you search, and the note you write.",
        "principles": [
            "Search is the first thing on the page; the list answers as you type",
            "Tags are chips everywhere: the same shape to filter by and to add",
            "One accent colour, for the one thing to do on each screen",
        ],
        "screens": [
            {
                "id": "notes",
                "task_id": "t2",
                "name": "Notes",
                "platform": "both",
                "purpose": "Find a note: search it, or narrow the list by a tag.",
                "layout": "Title and New note on top, search under it, tags beside, notes below.",
                "components": ["Search box", "Tag list", "Note cards", "New note"],
                "states": ["empty: no notes yet", "no match: try fewer words", "loading"],
                "interactions": ["Typing searches", "A tag filters", "A card opens the note"],
                "mocks": {"web": NOTES_WEB, "mobile": NOTES_MOBILE},
            },
            {
                "id": "edit",
                "task_id": "t3",
                "name": "Edit note",
                "platform": "web",
                "purpose": "Write a note and tag it.",
                "layout": "The title large, the body under it, tags as chips, Save at the end.",
                "components": ["Title", "Body", "Tag input", "Save", "Cancel"],
                "states": ["new", "saving", "saved", "could not save"],
                "interactions": ["Enter adds a tag", "Save stores and goes back to the list"],
                "mock": EDIT_WEB,
            },
        ],
    }

    def build(req: Any) -> dict[str, Any]:
        phase = _phase_of(req)
        if phase == 1:
            main = SEED["app/main.py"].replace(
                "from app.store import NOTES\n", "from app.notes import router as notes\n"
            )
            main = main.split("\n\n@app.get")[0] + "\napp.include_router(notes)\n"
            return {
                "summary": "Search on GET /api/notes: words in the title or body, and a tag.",
                "phase_complete": True,
                "changes": [
                    {"path": "app/notes.py", "content": SEARCH},
                    {"path": "app/main.py", "content": main},
                ],
            }
        if phase == 2:
            return {
                "summary": "web/index.html: the search box, the tag list and the cards.",
                "phase_complete": True,
                "changes": [{"path": "web/index.html", "content": LIST_PAGE}],
            }
        return {
            "summary": "web/edit.html: title, body, tags as chips, Save.",
            "phase_complete": True,
            "changes": [{"path": "web/edit.html", "content": EDIT_PAGE}],
        }

    def qa(req: Any) -> dict[str, Any]:
        if _context(req).get("stage") == 1:
            return {
                "summary": "Three cases: search, the tag filter, and the page itself.",
                "test_cases": [
                    {
                        "name": "search finds a word in the body",
                        "description": "GET /api/notes?q=search returns only the note saying it",
                    },
                    {
                        "name": "a tag narrows the list",
                        "description": "GET /api/notes?tag=home returns only the home notes",
                    },
                    {
                        "name": "the notes page is served",
                        "description": "GET / answers the page with its search box",
                    },
                ],
            }
        return {
            "summary": "tests/test_search.py, all three green.",
            "changes": [{"path": "tests/test_search.py", "content": TESTS}],
        }

    # what the supervisor says, gate by gate: one answer for all of them reads, on camera,
    # as a supervisor that is not looking
    reasons = {
        "backlog": ["Every part of the request has a task", "Nothing asked for is missing"],
        "architecture": [
            "Every task in the backlog has a phase",
            "The API change is additive: existing callers see the same list",
        ],
        "design": ["Both screens cover the backlog's tasks", "Empty and no-match states drawn"],
        "test cases": [
            "Each backlog task has a case that exercises it",
            "Nothing tests a behaviour the plan did not ask for",
        ],
        "written tests": ["All three cases are written and green", "They test through the API"],
        "deployment": [
            "The target matches the stack: one container, no state",
            "Secrets come from the environment, none in the files",
        ],
    }

    def supervise(req: Any) -> dict[str, Any]:
        found = re.search(r'"gate":\s*"([^"]+)"', req.prompt)
        return {
            "summary": "Covers the request and nothing beyond it.",
            "decision": "approve",
            "confidence": 0.91,
            "risk": "low",
            "reasons": reasons.get(found.group(1) if found else "", ["Small, additive change"]),
        }

    replies = {
        "po": backlog,
        "architect": plan,
        "designer": design,
        "backend": build,
        "web_ui": build,
        "mobile_ui": build,
        "qa": qa,
        "devops": {
            "summary": "Branch pushed, pull request opened.",
            "pr_title": "Notes page: write, search and tag notes",
            "pr_body": "Search on `GET /api/notes` (words and a tag), the notes page and the "
            "editor, as the Designer drew them. Deploys to ECS Fargate on merge: see "
            "`deployment/`. Covered by tests/test_search.py.",
        },
        "supervisor": supervise,
    }
    asides = {
        "analysis": {
            "summary": "A small FastAPI service with an API and no page yet.",
            "items": [
                {
                    "category": "product",
                    "title": "Notes over HTTP",
                    "detail": "GET /api/notes lists them; nothing to search or edit with yet.",
                },
                {
                    "category": "stack",
                    "title": "Python, FastAPI, uvicorn",
                    "detail": "Declared in pyproject.toml, version 0.3.0.",
                },
                {
                    "category": "modules",
                    "title": "app/main.py and an in-memory store",
                    "detail": "app/store.py holds the notes; no database yet.",
                },
                {
                    "category": "testing",
                    "title": "pytest with FastAPI's TestClient",
                    "detail": "tests/ mirrors app/.",
                },
            ],
        },
        "deploy": DEPLOY_PLAN,
        "deploy_write": {
            "summary": "The image, the Fargate task, the deploy script and the workflow.",
            "phase_complete": True,
            "changes": [{"path": p, "content": c} for p, c in DEPLOY_FILES.items()],
        },
    }
    return replies, asides


def the_outside(engine: Any, scratch: Path) -> tuple[demo_world.Telegram, demo_world.Jira]:
    """Telegram, Jira and a Git host, wired in where the real ones would be."""
    telegram, jira = demo_world.Telegram(), demo_world.Jira()
    engine.http_transport = demo_world.transport(telegram, jira)
    engine._git_host = demo_world.Host(  # noqa: SLF001 - the engine's own seam for a host
        a_remote(scratch / "remote"), f"https://github.com/acme/{PROJECT}"
    )
    store = engine.store
    # Jira, connected the way Settings -> Jira would leave it
    engine.update_jira_settings(
        site_url=demo_world.JIRA_SITE, email="ada@acme.dev", token="demo-jira-token"
    )
    # the bot, and the person already linked to it -- the linking is its own picture in
    # the README; the recording starts from somebody who did it last week
    store.set_setting("notify.telegram.token", "777:demo", secret=True)
    store.set_setting("notify.telegram", {"bot_username": demo_world.BOT["username"]})
    from slipwright.notify.models import ChatLink
    from slipwright.schemas.job import utcnow
    from slipwright.store.chat import new_link_id

    person = demo_world.PERSON
    store.save_chat_link(
        ChatLink(
            id=new_link_id(),
            owner_id="",
            user_id="anonymous",
            channel="telegram",
            external_id=str(person["id"]),
            address={"chat_id": person["id"]},
            label=str(person["first_name"]),
            linked_at=utcnow(),
        )
    )
    # The bot speaks Turkish unless told otherwise: that is who it was written for. The
    # README is read in English, so the recording's bot is told otherwise.
    from slipwright.notify import core

    defaults = core.Notifier.__init__.__kwdefaults__
    if defaults is not None:
        defaults["lang"] = "en"
    return telegram, jira


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
    telegram, jira = the_outside(engine, scratch)

    base = f"http://127.0.0.1:{args.port}"
    print("\n  Demo set up. No API key is used; every role answers from the script.\n")
    print(f"  Open:  {base}/agents")
    print(f"  Then:  New project -> Local checkout -> {PROJECT}, and ask for")
    print(f'         "{REQUEST}"')
    print(f"  Phone: {base}/demo/telegram    Board: {base}/demo/jira\n")
    # flushed, because uvicorn's own logging starts a line later and would bury the link
    print(
        "  Ctrl-C stops the server." + ("" if args.keep else f"  {scratch} is removed after.\n"),
        flush=True,
    )

    try:
        # a recording has nobody to log in: the state directory is a throwaway and the
        # server is bound to this machine
        # and no price refresh: it reads a table off GitHub, and the demo is offline
        app = create_app(engine, require_auth=False, price_refresh_s=0)
        demo_world.pages(app, telegram, jira)
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
