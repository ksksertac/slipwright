"""T11.1-T11.3: the project brief — analysis, intake, editing and who reads it."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import BriefIsRunning, Engine
from slipwright.roles.discovery import repository_is_empty
from slipwright.schemas.brief import BriefEdit, BriefItem, BriefState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _empty_repo(tmp_path: Path) -> Path:
    path = tmp_path / "empty"
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q", "-b", "main"], check=True)
    (path / "README.md").write_bytes(b"# nothing yet\n")
    return path


# --- what counts as empty -----------------------------------------------------------------


def test_a_readme_only_checkout_is_empty(tmp_path: Path) -> None:
    path = _empty_repo(tmp_path)
    assert repository_is_empty(path)
    (path / "main.py").write_text("print(1)\n")
    assert not repository_is_empty(path)


def test_the_fixture_repository_is_empty_until_code_arrives(repo: Path) -> None:
    assert repository_is_empty(repo)  # the fixture holds only README.md
    (repo / "app.py").write_text("x = 1\n")
    assert not repository_is_empty(repo)


# --- analysis of an existing checkout ------------------------------------------------------


def test_analysis_proposes_items_a_person_then_edits_and_approves(
    engine: Engine, client: TestClient, repo: Path
) -> None:
    (repo / "app.py").write_text("x = 1\n")  # so the repository is not 'empty'
    project = engine.create_project(Project(name="p", repo_path=repo))

    first = client.get(f"/api/projects/{project.id}/brief").json()
    assert first["kind"] == "analysis"
    assert first["brief"]["state"] == "empty"
    assert first["brief"]["items"] == []

    started = client.post(f"/api/projects/{project.id}/brief/analysis")
    assert started.status_code == 202
    view = client.get(f"/api/projects/{project.id}/brief").json()
    assert view["brief"]["state"] == "proposed"
    items = view["brief"]["items"]
    assert len(items) == 2
    assert view["brief"]["summary"] == "scripted analysis"
    assert {i["source"] for i in items} == {"analysis"}

    # the person strikes one line out, corrects the other, and approves the rest
    kept = dict(items[0], title="Python 3.12 and FastAPI")
    saved = client.put(
        f"/api/projects/{project.id}/brief", json={"items": [kept], "approve": True}
    )
    assert saved.status_code == 200
    brief = saved.json()["brief"]
    assert brief["state"] == "ready"
    assert [i["title"] for i in brief["items"]] == ["Python 3.12 and FastAPI"]
    assert brief["approved_at"] is not None


def test_only_an_approved_brief_reaches_an_agent(engine: Engine, repo: Path) -> None:
    (repo / "app.py").write_text("x = 1\n")
    project = engine.create_project(Project(name="p", repo_path=repo))
    engine.start_analysis(project.id)
    engine.execute_analysis(project.id)

    # proposed, not approved: a job started now is told nothing
    assert engine.create_job("do a thing", project_id=project.id).data.brief == []

    engine.save_brief(project.id, BriefEdit(items=engine.brief(project.id).items, approve=True))
    job = engine.create_job("do another thing", project_id=project.id)
    assert [i["title"] for i in job.data.brief] == ["Python and FastAPI", "pytest"]
    assert "category" in job.data.brief[0] and "source" not in job.data.brief[0]


def test_the_brief_is_in_every_role_prompt(engine: Engine, repo: Path) -> None:
    from slipwright.roles.common import base_context

    (repo / "app.py").write_text("x = 1\n")
    project = engine.create_project(Project(name="p", repo_path=repo))
    engine.start_analysis(project.id)
    engine.execute_analysis(project.id)
    engine.save_brief(project.id, BriefEdit(items=engine.brief(project.id).items, approve=True))
    job = engine.create_job("do a thing", project_id=project.id)

    context = base_context(job, instructions="x")
    assert [i["title"] for i in context["project"]] == ["Python and FastAPI", "pytest"]


def test_a_second_analysis_is_refused_while_one_is_running(engine: Engine, repo: Path) -> None:
    (repo / "app.py").write_text("x = 1\n")
    project = engine.create_project(Project(name="p", repo_path=repo))
    engine.start_analysis(project.id)
    with pytest.raises(BriefIsRunning):
        engine.start_analysis(project.id)


def test_a_failed_analysis_says_why_and_can_be_run_again(engine: Engine, repo: Path) -> None:
    (repo / "app.py").write_text("x = 1\n")
    project = engine.create_project(Project(name="p", repo_path=repo))
    engine.provider.discovery.pop("analysis")  # the model answers with nothing usable
    engine.start_analysis(project.id)
    brief = engine.execute_analysis(project.id)
    assert brief.state is BriefState.FAILED
    assert brief.error

    engine.provider.discovery["analysis"] = {
        "summary": "second time",
        "items": [{"category": "stack", "title": "Python", "detail": ""}],
    }
    engine.start_analysis(project.id)
    assert engine.execute_analysis(project.id).state is BriefState.PROPOSED


def test_approving_an_empty_brief_is_refused(
    engine: Engine, client: TestClient, repo: Path
) -> None:
    (repo / "app.py").write_text("x = 1\n")
    project = engine.create_project(Project(name="p", repo_path=repo))
    resp = client.put(f"/api/projects/{project.id}/brief", json={"items": [], "approve": True})
    assert resp.status_code == 400

    # saving without approving is fine: the person can come back to it
    resp = client.put(
        f"/api/projects/{project.id}/brief",
        json={"items": [BriefItem(title="draft").model_dump(mode="json")], "approve": False},
    )
    assert resp.status_code == 200
    assert resp.json()["brief"]["state"] == "proposed"


# --- intake for an empty repository --------------------------------------------------------


def test_intake_asks_then_ends_with_the_story(
    engine: Engine, client: TestClient, tmp_path: Path
) -> None:
    project = engine.create_project(Project(name="new thing", repo_path=_empty_repo(tmp_path)))
    assert client.get(f"/api/projects/{project.id}/brief").json()["kind"] == "intake"

    started = client.post(f"/api/projects/{project.id}/brief/intake", json={"answers": {}})
    assert started.status_code == 202
    brief = client.get(f"/api/projects/{project.id}/brief").json()["brief"]
    questions = brief["intake"]["rounds"][0]["questions"]
    assert [q["question"] for q in questions] == ["What is it for?", "Who uses it?"]
    assert brief["intake"]["done"] is False

    answers = {q["id"]: f"answer to {q['question']}" for q in questions}
    client.post(f"/api/projects/{project.id}/brief/intake", json={"answers": answers})
    brief = client.get(f"/api/projects/{project.id}/brief").json()["brief"]
    assert brief["intake"]["done"] is True
    assert brief["intake"]["story"] == "Build the thing the answers describe."
    assert [q["answer"] for q in brief["intake"]["rounds"][0]["questions"]] == list(
        answers.values()
    )
    assert [i["source"] for i in brief["items"]] == ["intake"]
    assert brief["state"] == "proposed"  # the person still approves it


def test_intake_answers_before_any_question_are_refused(
    engine: Engine, client: TestClient, tmp_path: Path
) -> None:
    project = engine.create_project(Project(name="new thing", repo_path=_empty_repo(tmp_path)))
    resp = client.post(
        f"/api/projects/{project.id}/brief/intake", json={"answers": {"nope": "x"}}
    )
    assert resp.status_code == 400


def test_the_last_round_has_to_finish(engine: Engine, tmp_path: Path) -> None:
    project = engine.create_project(Project(name="new thing", repo_path=_empty_repo(tmp_path)))
    # a model that would happily ask forever, and a brief already at its last round
    engine.provider.discovery["intake"] = {
        "summary": "more questions",
        "questions": [{"question": "and another thing?", "why": "", "hint": ""}],
        "ready": False,
    }
    engine.start_intake(project.id)
    for _ in range(3):
        engine.execute_intake(project.id)
        brief = engine.brief(project.id)
        answers = {q.id: "yes" for q in brief.intake.rounds[-1].questions}
        engine.start_intake(project.id, answers)
    brief = engine.brief(project.id)
    assert len(brief.intake.rounds) == brief.intake.max_rounds
    assert brief.intake.done is False  # this model never finishes...

    # ...so the round that must finish is answered with a story, and it is taken
    engine.provider.discovery["intake"] = {
        "summary": "forced to finish",
        "questions": [{"question": "one more?", "why": "", "hint": ""}],
        "ready": False,
        "story": "Build what the answers describe.",
        "items": [{"category": "product", "title": "What it is for", "detail": ""}],
    }
    brief = engine.execute_intake(project.id)
    assert brief.intake is not None and brief.intake.done is True
    assert brief.intake.story == "Build what the answers describe."
    assert len(brief.items) == 1


def test_the_brief_dies_with_its_project(engine: Engine, repo: Path) -> None:
    (repo / "app.py").write_text("x = 1\n")
    project = engine.create_project(Project(name="p", repo_path=repo))
    engine.start_analysis(project.id)
    engine.execute_analysis(project.id)
    engine.store.delete_project(project.id)
    assert engine.store.get_brief(project.id).items == []
