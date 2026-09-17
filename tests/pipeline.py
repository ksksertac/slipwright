"""Shared helpers for tests that drive the whole pipeline with a scripted provider."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from slipwright.engine import Engine
from slipwright.githost import CiState, CiStatus
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.roles.specialists import DEVELOPER_ROLES
from slipwright.schemas.profile import Profile, RoleName, load_profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"
PY = sys.executable
TRUE = f'"{PY}" -c "print(1)"'
FALSE = f'"{PY}" -c "raise SystemExit(1)"'


class FakeHost:
    def push(self, worktree: Path, branch: str) -> None:
        pass

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        return "https://example.test/pr/1"

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        return CiStatus(CiState.SUCCESS, summary="ci: success")


BREAKDOWN: dict[str, Any] = {
    "epics": [
        {
            "id": "e1",
            "title": "Health endpoint",
            "stories": [
                {
                    "id": "s1",
                    "title": "As an operator I can probe liveness",
                    "tasks": [
                        {"id": "t1", "title": "Add route"},
                        {"id": "t2", "title": "Add response model"},
                    ],
                },
                {
                    "id": "s2",
                    "title": "As an operator I see the version",
                    "tasks": [{"id": "t3", "title": "Expose version"}],
                },
            ],
        },
        {
            "id": "e2",
            "title": "Documentation",
            "stories": [
                {
                    "id": "s3",
                    "title": "As a developer I read about /health",
                    "tasks": [{"id": "t4", "title": "Document it"}],
                }
            ],
        },
    ]
}


def default_backlog(tasks: int) -> dict[str, Any]:
    """One epic, one story, ``tasks`` tasks with ids t1..tN."""
    return {
        "epics": [
            {
                "id": "e1",
                "title": "Request",
                "stories": [
                    {
                        "id": "s1",
                        "title": "As a user I get the request",
                        "tasks": [
                            {"id": f"t{i + 1}", "title": f"step {i + 1}"} for i in range(tasks)
                        ],
                    }
                ],
            }
        ]
    }


def task_ids(breakdown: dict[str, Any]) -> list[str]:
    return [t["id"] for e in breakdown["epics"] for s in e["stories"] for t in s["tasks"]]


def set_plan(provider: ScriptedProvider, seed: Profile, phases: list[dict[str, Any]]) -> None:
    """Script the PO (one task per phase, ids t1..tN) and the Architect (the phases,
    each mapped to its task) so older tests can describe a plan as a phase list."""
    backlog = default_backlog(len(phases))
    provider.replies[RoleName.PO] = {"summary": f"{len(phases)} tasks", "breakdown": backlog}
    provider.replies[RoleName.ARCHITECT] = {
        "summary": f"{len(phases)} phases",
        "profile": seed.model_dump(mode="json"),
        "decisions": [],
        "phases": [{**phase, "task_id": f"t{i + 1}"} for i, phase in enumerate(phases)],
    }


def full_provider(
    seed: Profile,
    phases: int = 4,
    breakdown: dict[str, Any] | None = None,
    domains: list[str] | None = None,
) -> ScriptedProvider:
    """PO returns ``breakdown`` (or a default one with ``phases`` tasks); the Architect
    returns one phase per task, in order, tagged with ``domains`` (default general)."""
    p = canned(seed)
    backlog = breakdown if breakdown is not None else default_backlog(phases)
    ids = task_ids(backlog)
    p.replies[RoleName.PO] = {"summary": f"{len(ids)} tasks", "breakdown": backlog}
    p.replies[RoleName.ARCHITECT] = {
        "summary": f"{len(ids)} phases",
        "profile": seed.model_dump(mode="json"),
        "decisions": ["write OK"],
        "phases": [
            {
                "goal": f"step {i + 1}",
                "files": ["OK"],
                "task_id": tid,
                "domain": (domains[i % len(domains)] if domains else "general"),
            }
            for i, tid in enumerate(ids)
        ],
    }
    for role in DEVELOPER_ROLES:
        p.replies[role] = {
            "summary": "wrote OK",
            "phase_complete": True,
            "changes": [{"path": "OK", "content": "yes\n"}],
        }
    p.replies[RoleName.QA] = lambda req: (
        {"summary": "cases", "test_cases": [{"name": "smoke", "description": "OK is yes"}]}
        if '"stage": 1' in req.prompt
        else {"summary": "tests", "changes": [{"path": "tests/t.txt", "content": "ok\n"}]}
    )
    return p


def full_engine(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider, **kw: Any
) -> Engine:
    ws = Workspace(worktrees_root, PortAllocator(start=8300, end=8399))
    if "git_host" not in kw:
        kw["git_host"] = FakeHost()
    kw.setdefault("supervisor_mode", "manual")  # the supervisor has its own tests (T9.8)
    kw.setdefault("retry_backoff_s", 0.0)  # retries are tested on their own (T9.7)
    return Engine(store, ws, seed_profile=seed, provider=provider, ci_poll_s=0.0, **kw)


def full_seed() -> Profile:
    """The example profile with build and test commands that always pass."""
    return load_profile(EXAMPLE).model_copy(update={"build_cmd": TRUE, "test_cmd": TRUE})
