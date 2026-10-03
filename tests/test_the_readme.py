"""The Architect draws the product, and writes the README the pull request carries.

A finished React Native app once went out with a README that was an audit of what could
not be verified: nobody owned the file, and every docs task wrote into it what it was told
to record. Now the Architect draws the architecture with the plan -- shown at the gate and
on its step -- and writes the README once every phase is built.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slipwright.engine import Engine
from slipwright.providers import ModelRequest
from slipwright.providers.scripted import ScriptedProvider
from slipwright.providers.scripted import _context as _sent
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.steps import step_detail
from slipwright.store import JobStore
from slipwright.workspace import git as g
from tests.pipeline import full_engine, full_provider

DIAGRAM = "flowchart LR\n  app[App · React Native] -->|Bluetooth| peer[Other phones]"

README = (
    "# Math Challenge\n\nA quiz for grades 3 to 12.\n\n## Architecture\n\n"
    f"```mermaid\n{DIAGRAM}\n```\n"
)


def _provider(seed: Profile, readme: Any = None) -> ScriptedProvider:
    provider = full_provider(seed, phases=1)
    plan = provider.replies[RoleName.ARCHITECT]
    assert isinstance(plan, dict)
    plan["diagram"] = DIAGRAM
    provider.discovery["readme"] = (
        readme if readme is not None else {"summary": "the README", "readme": README}
    )
    return provider


def _to_the_end(engine: Engine, repo: Path) -> Job:
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("a math quiz", project_id=project.id).id)
    while job.state not in (JobState.DONE, JobState.FAILED):
        job = engine.approve(job.id)
    return job


def _context(request: ModelRequest) -> dict[str, Any]:
    return _sent(request)


def test_the_plan_carries_the_architects_drawing(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    engine = full_engine(store, worktrees_root, seed, _provider(seed))
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("a math quiz", project_id=project.id).id)
    job = engine.approve(job.id)  # backlog -> the plan waits at its gate

    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert (job.data.plan or {})["diagram"] == DIAGRAM
    # an edit of the phases at the gate keeps the drawing
    plan = job.data.plan or {}
    job = engine.set_plan(job.id, {"phases": plan["phases"]})
    assert (job.data.plan or {})["diagram"] == DIAGRAM


def test_the_architecture_step_opens_on_the_drawing(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    engine = full_engine(store, worktrees_root, seed, _provider(seed))
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("a math quiz", project_id=project.id).id)
    job = engine.approve(job.id)

    for key in ("architecture", "architecture_gate"):
        detail = step_detail(job, key)
        assert detail is not None
        first = detail.groups[0]
        assert first.key == "diagram"
        assert [i.kind for i in first.items] == ["diagram"]
        assert first.items[0].detail == DIAGRAM


def test_a_plan_without_a_drawing_shows_no_empty_one(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    """Plans written before drawings have none; the panel does not announce the lack."""
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.approve(
        engine.start(engine.create_job("a math quiz", project_id=project.id).id).id
    )

    detail = step_detail(job, "architecture")
    assert detail is not None
    assert "diagram" not in [g.key for g in detail.groups]


def test_the_architect_writes_the_readme_the_pull_request_carries(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    provider = _provider(seed)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _to_the_end(engine, repo)

    assert job.state is JobState.DONE
    assert job.data.pr_url is not None
    assert job.worktree_path is not None
    readme = (job.worktree_path / "README.md").read_bytes()
    assert readme == README.encode()
    assert b"\r\n" not in readme
    # committed on the branch, so it is in the pull request and not only on disk
    log = g.run(job.worktree_path, "log", "--format=%s", "-n", "20").stdout
    assert "slipwright: README" in log
    assert any((t.note or "").startswith("architect: README written") for t in job.history)

    # it was asked with the drawing and the build facts in hand, after every phase
    asked = [r for r in provider.requests if "the development you planned is built" in r.prompt]
    assert len(asked) == 1
    context = _context(asked[0])
    assert context["plan"]["diagram"] == DIAGRAM
    assert context["project"]["build_cmd"] == seed.build_cmd
    assert "worktree" in context


def test_a_readme_that_cannot_be_written_does_not_stop_the_pull_request(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    engine = full_engine(store, worktrees_root, seed, _provider(seed, readme="not json"))
    job = _to_the_end(engine, repo)

    assert job.state is JobState.DONE
    assert job.data.pr_url is not None
    assert any(
        (t.note or "").startswith("architect: the README could not be written") for t in job.history
    )


def test_no_phase_is_planned_to_write_the_readme() -> None:
    """The Architect is told the README is its own, written at the end, and that a task's
    findings go under docs/ -- the README is not a place to keep a report."""
    from slipwright.roles.architect import INSTRUCTIONS, README_INSTRUCTIONS

    assert "no phase lists it among its files" in INSTRUCTIONS
    assert "never in the README" in INSTRUCTIONS
    assert "`diagram`" in INSTRUCTIONS
    assert "```mermaid" in README_INSTRUCTIONS
    assert "not a report" in README_INSTRUCTIONS
