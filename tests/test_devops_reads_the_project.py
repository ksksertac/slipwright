"""DevOps writes a pipeline from the project it is for, and does not give up on it.

It used to be shown only ``deployment/``. Asked for a pipeline that packages a desktop
app for three platforms, it had no ``package.json`` to take the commands from and no
current workflow whose checks it had to keep; it said so five times over -- once per part
it was asked for -- wrote nothing, and the development failed at "devops wrote no
deployment files".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from slipwright.engine import Engine
from slipwright.providers import ModelRequest
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine
from tests.test_phase11_deploy import AWS_PLAN, WRITTEN, _provider, _to_deploy_gate

PACKAGE = {"name": "deskapp", "scripts": {"package": "electron-builder --win --mac --linux"}}
WORKFLOW = "name: ci\non: [push]\njobs:\n  lint:\n    steps:\n      - run: npm run lint\n"
WRITE = "Write the deployment files that were approved"
REFUSAL = "The packaging commands and the current CI are not in the context; nothing written."


def _project(repo: Path) -> None:
    """A desktop app with a package script and a workflow, committed: a development
    branches from what is committed, not from what lies in the checkout."""
    (repo / "package.json").write_text(json.dumps(PACKAGE), encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "the app"], check=True)


def _engine(store: JobStore, worktrees_root: Path, seed: Profile, write: Any) -> Engine:
    provider = _provider(seed, AWS_PLAN)
    provider.discovery["deploy_write"] = write
    return full_engine(store, worktrees_root, seed, provider)


def _asked(engine: Engine, words: str) -> list[ModelRequest]:
    return [r for r in engine.provider.requests if words in r.prompt]  # type: ignore[attr-defined]


def test_devops_is_shown_the_manifests_and_the_pipeline_it_rewrites(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    _project(repo)
    engine = _engine(store, worktrees_root, seed, WRITTEN)

    job = engine.approve(_to_deploy_gate(engine, repo).id)

    assert job.state is JobState.DONE, job.history[-1].note
    for request in (*_asked(engine, "propose how this project"), *_asked(engine, WRITE)):
        assert "electron-builder --win --mac --linux" in request.prompt  # package.json
        assert "npm run lint" in request.prompt  # the check the current workflow runs
        assert "current_pipeline" in request.prompt


def test_an_answer_with_no_files_is_asked_once_more_with_the_reason(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    answers = iter([{"summary": REFUSAL, "changes": []}, WRITTEN])
    engine = _engine(store, worktrees_root, seed, lambda req: next(answers))

    job = engine.approve(_to_deploy_gate(engine, repo).id)

    assert job.state is JobState.DONE, job.history[-1].note
    assert len(job.data.deploy_written) == 3
    first, second = _asked(engine, WRITE)
    assert "previous_answer_problem" not in first.prompt
    assert "You wrote no files" in second.prompt
    assert any(t.note == "devops: wrote no files; asking once more" for t in job.history)


def test_an_answer_that_stays_empty_fails_after_one_more_ask_not_five(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    engine = _engine(store, worktrees_root, seed, lambda req: {"summary": REFUSAL, "changes": []})

    job = engine.approve(_to_deploy_gate(engine, repo).id)

    assert job.state is JobState.FAILED
    assert job.history[-1].note == "devops wrote no deployment files"
    assert len(_asked(engine, WRITE)) == 2
