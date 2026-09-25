"""The worked example a new account starts with.

A person who has just signed up has no model key yet, so no agent can run and an empty
dashboard is all Slipwright could otherwise show them -- which says nothing about what it
does. Instead they arrive to one finished development they can read: a backlog, a plan
with its decisions, phases with the files they touched, test cases, a standards review
and the whole activity feed.

It is **data, not a run**. Nothing is executed, no repository is cloned, no worktree is
made and not one token is spent. It costs a handful of rows and is deleted with one
click, which is the point: the example should be easy to throw away once the person has
a project of their own.

The prose is written in English and goes through the ordinary translation bridge
(``slipwright/translate.py``), so it follows the TR/EN switch like any other agent text
rather than being written twice.
"""

from __future__ import annotations

import logging
from typing import Any

from slipwright.schemas.job import Job, JobData, JobState, Transition, new_job_id, utcnow
from slipwright.schemas.project import Project
from slipwright.store import JobStore

log = logging.getLogger(__name__)

DEMO_NAME = "Example: a Notes app"
DEMO_REQUEST = (
    "Build a small Notes app, end to end: a REST API over SQLite, a web page to list, "
    "search, write and delete notes, unit and end-to-end tests, and a Dockerfile."
)

_EPIC = new_job_id
_BACKLOG: dict[str, Any] = {
    "epics": [
        {
            "id": "demo-e1",
            "title": "Notes, stored and served",
            "description": "One note has a title, a body and the times it was written and changed.",
            "stories": [
                {
                    "id": "demo-s1",
                    "title": "As a user I can write a note and find it again",
                    "description": "Create, read, update and delete, with search and paging.",
                    "tasks": [
                        {
                            "id": "demo-t1",
                            "title": "The note itself, and the table it lives in",
                            "description": "A title of 1 to 120 characters, a body, and a "
                            "reversible migration.",
                            "phase": 1,
                        },
                        {
                            "id": "demo-t2",
                            "title": "The REST surface for notes",
                            "description": "List with search and paging, fetch one, create, "
                            "update, delete. 422 on a bad body, 404 on a note that is not there.",
                            "phase": 2,
                        },
                    ],
                }
            ],
        },
        {
            "id": "demo-e2",
            "title": "Something to use it with",
            "description": "A page that does the whole job without reading the API docs.",
            "stories": [
                {
                    "id": "demo-s2",
                    "title": "As a user I can do all of it from the browser",
                    "description": "List, search, write, edit and delete, with the empty and "
                    "failed states drawn rather than left blank.",
                    "tasks": [
                        {
                            "id": "demo-t3",
                            "title": "The note list, with search and an empty state",
                            "description": "What the page shows before anything has been "
                            "written matters as much as what it shows after.",
                            "phase": 3,
                        },
                        {
                            "id": "demo-t4",
                            "title": "Writing, editing and deleting a note",
                            "description": "Deleting asks first; an edit that fails says so "
                            "without losing what was typed.",
                            "phase": 4,
                        },
                    ],
                }
            ],
        },
    ]
}

_PLAN: dict[str, Any] = {
    "summary": (
        "The worktree is empty, so every phase below builds something that is not there "
        "yet. The API comes first because the page has nothing to show without it, and "
        "the tests are written against the behaviour rather than the implementation, so "
        "they survive the next change."
    ),
    "decisions": [
        "SQLite through a migration rather than a created-on-boot schema: a database that "
        "is only ever built from scratch cannot be upgraded.",
        "Search is a LIKE over title and body. It is enough for a few thousand notes and "
        "honest about it; full-text search can come when that stops being true.",
        "The page talks to the same REST surface anything else would, so there is no "
        "private back door that only the browser can use.",
    ],
    "phases": [
        {
            "goal": "The note model and its first migration",
            "files": ["app/models.py", "migrations/0001_notes.py"],
            "task_id": "demo-t1",
            "domain": "backend",
        },
        {
            "goal": "The /api/notes surface, with search and paging",
            "files": ["app/api.py", "app/schemas.py"],
            "task_id": "demo-t2",
            "domain": "backend",
        },
        {
            "goal": "The note list, its search box and its empty state",
            "files": ["web/src/NoteList.tsx", "web/src/api.ts"],
            "task_id": "demo-t3",
            "domain": "web",
        },
        {
            "goal": "Writing, editing and deleting, with a confirmation",
            "files": ["web/src/NoteForm.tsx", "web/src/DeleteDialog.tsx"],
            "task_id": "demo-t4",
            "domain": "web",
        },
    ],
    "breakdown": _BACKLOG,
}

_TEST_CASES: list[dict[str, str]] = [
    {
        "name": "A note without a title is refused",
        "description": "POST /api/notes with an empty title answers 422 and writes nothing.",
    },
    {
        "name": "Search finds a note by a word in its body",
        "description": "Two notes exist; searching for a word in one returns only that one.",
    },
    {
        "name": "A note that is not there answers 404",
        "description": "GET /api/notes/<unknown> answers 404 rather than 500 or an empty note.",
    },
    {
        "name": "Write a note, see it listed, delete it",
        "description": "The whole round trip through the page, in a real browser.",
    },
]

#: ``(from state, to state, note, detail)``. The story the activity feed tells.
_HISTORY: list[tuple[JobState, JobState, str, str | None]] = [
    (JobState.CREATED, JobState.BACKLOG, "job started", None),
    (
        JobState.BACKLOG,
        JobState.AWAITING_BACKLOG_APPROVAL,
        "po: backlog ready — 2 epics, 2 stories, 4 tasks",
        None,
    ),
    (JobState.AWAITING_BACKLOG_APPROVAL, JobState.ARCHITECTURE, "approved", None),
    (
        JobState.ARCHITECTURE,
        JobState.AWAITING_ARCHITECTURE_APPROVAL,
        "architect: plan ready — 4 phases, 3 decisions",
        None,
    ),
    (JobState.AWAITING_ARCHITECTURE_APPROVAL, JobState.DEVELOPING, "approved", None),
    (
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        "backend phase 1/4: Added the Note model and a reversible migration. (2 files)",
        None,
    ),
    (JobState.BUILD_GATE, JobState.REVIEW, "build gate passed for phase 1/4", None),
    (JobState.REVIEW, JobState.DEVELOPING, "review phase 1/4: clean", None),
    (
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        "backend phase 2/4: The notes endpoints, with search and paging. (2 files)",
        None,
    ),
    (JobState.BUILD_GATE, JobState.REVIEW, "build gate passed for phase 2/4", None),
    (
        JobState.REVIEW,
        JobState.DEVELOPING,
        "review phase 2/4: 1 violation(s), 0 blocking, 1 advisory",
        None,
    ),
    (
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        "web_ui phase 3/4: The note list, its search box and its empty state. (2 files)",
        None,
    ),
    (JobState.BUILD_GATE, JobState.REVIEW, "build gate passed for phase 3/4", None),
    (JobState.REVIEW, JobState.DEVELOPING, "review phase 3/4: clean", None),
    (
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        "web_ui phase 4/4: Writing, editing and deleting, with a confirmation. (2 files)",
        None,
    ),
    (JobState.BUILD_GATE, JobState.QA, "build gate passed for phase 4/4", None),
    (JobState.QA, JobState.AWAITING_TEST_APPROVAL, "qa: 4 test cases proposed", None),
    (JobState.AWAITING_TEST_APPROVAL, JobState.QA, "approved 4 test cases", None),
    (
        JobState.QA,
        JobState.AWAITING_TEST_APPROVAL,
        "qa: tests written and green (3 files) — Unit tests for the model and the search, "
        "and one end-to-end pass through the page.",
        None,
    ),
    (JobState.AWAITING_TEST_APPROVAL, JobState.DEVOPS, "approved", None),
    (
        JobState.DEVOPS,
        JobState.DONE,
        "nothing was pushed: the checkout /example/notes-app has no remote. Branch "
        "slipwright/example is ready there — merge it with `git merge slipwright/example`, "
        "or set the project's GitHub repository so the next development pushes and opens a "
        "pull request",
        None,
    ),
]

_REVIEWS: list[dict[str, Any]] = [
    {
        "phase": 2,
        "round": 0,
        "mode": "advisory",
        "summary": "The endpoints follow the standards; one thing is worth knowing about.",
        "violations": [
            {
                "section": "Paging",
                "file": "app/api.py",
                "line": 41,
                "severity": "advisory",
                "message": "The list endpoint has no upper bound on its page size.",
                "fix": "Cap it, so one request cannot ask for every note at once.",
            }
        ],
        "blocking": 0,
        "advisory": 1,
        "verdict": "passed (advisory)",
    }
]


def seed_demo_project(store: JobStore, owner_id: str) -> Project | None:
    """Give this account the worked example. Returns ``None`` when it already has one.

    Never raises: an account is worth more than its example, so a failure here is logged
    and the person simply arrives to an empty dashboard.
    """
    try:
        if any(p.is_demo for p in store.list_projects(owner_id)):
            return None
        project = store.create_project(
            Project(
                name=DEMO_NAME,
                description=(
                    "A finished development, to read rather than run. Delete it whenever "
                    "you like."
                ),
                owner_id=owner_id,
                is_demo=True,
                language="en",
            )
        )
        store.create(_demo_job(project))
        return project
    except Exception:  # noqa: BLE001 - a missing example must not break signing up
        log.exception("could not seed the example project for %s", owner_id)
        return None


def _demo_job(project: Project) -> Job:
    """The finished development, history and all, written in one go."""
    at = utcnow()
    history = [
        Transition(from_state=a, to_state=b, at=at, note=note, detail=detail)
        for a, b, note, detail in _HISTORY
    ]
    return Job(
        id=new_job_id(),
        project_id=project.id,
        owner_id=project.owner_id,
        request=DEMO_REQUEST,
        # no checkout: nothing here is ever executed, so there is nothing to execute in
        repo_path=project.repo_path or "/example/notes-app",
        state=JobState.DONE,
        created_at=at,
        history=history,
        data=JobData(
            language="en",
            backlog=_BACKLOG,
            plan=_PLAN,
            phase_index=len(_PLAN["phases"]),
            test_cases=list(_TEST_CASES),
            qa_stage=2,
            reviews=list(_REVIEWS),
        ),
    )


__all__ = ["DEMO_NAME", "DEMO_REQUEST", "seed_demo_project"]
