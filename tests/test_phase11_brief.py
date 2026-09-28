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


# --- the first development waits for the brief ----------------------------------------------


def test_the_first_development_waits_for_the_brief(
    engine: Engine, client: TestClient, repo: Path
) -> None:
    """The wizard's last step used to start the job straight away, which meant the brief
    never ran and the whole team planned and built without knowing what the project was.
    It waits on the project until somebody approves what the agents will be told."""
    (repo / "app.py").write_text("x = 1\n")
    made = client.post(
        "/api/projects",
        json={"name": "p", "repo_path": str(repo), "pending_request": "add a login page"},
    )
    assert made.status_code == 201
    project_id = made.json()["id"]

    # nothing is running: the request is on the project, not in a job
    assert client.get(f"/api/projects/{project_id}/jobs").json() == []
    view = client.get(f"/api/projects/{project_id}/brief").json()
    assert view["pending_request"] == "add a login page"

    engine.start_analysis(project_id)
    engine.execute_analysis(project_id)
    items = [i.model_dump(mode="json") for i in engine.brief(project_id).items]

    # saving a draft is not approving, so it still waits
    client.put(f"/api/projects/{project_id}/brief", json={"items": items, "approve": False})
    assert client.get(f"/api/projects/{project_id}/jobs").json() == []

    approved = client.put(
        f"/api/projects/{project_id}/brief", json={"items": items, "approve": True}
    )
    assert approved.status_code == 200
    jobs = client.get(f"/api/projects/{project_id}/jobs").json()
    assert [j["request"] for j in jobs] == ["add a login page"]
    # and it started knowing what the project is, which was the whole point
    assert jobs[0]["data"]["brief"], "the development began with an empty brief"

    # claimed once: approving again does not start a second development
    assert approved.json()["pending_request"] == ""
    client.put(f"/api/projects/{project_id}/brief", json={"items": items, "approve": True})
    assert len(client.get(f"/api/projects/{project_id}/jobs").json()) == 1


def test_a_project_with_nothing_pending_starts_nothing(
    engine: Engine, client: TestClient, repo: Path
) -> None:
    """Approving a brief on a project made without a first request is just approving."""
    (repo / "app.py").write_text("x = 1\n")
    project = engine.create_project(Project(name="p", repo_path=repo))
    engine.start_analysis(project.id)
    engine.execute_analysis(project.id)
    items = [i.model_dump(mode="json") for i in engine.brief(project.id).items]
    client.put(f"/api/projects/{project.id}/brief", json={"items": items, "approve": True})
    assert client.get(f"/api/projects/{project.id}/jobs").json() == []


def test_a_new_repository_is_named_after_the_project(client: TestClient) -> None:
    """A project called "Note app" opens a repository called "note-app": the wizard
    derives it, because a repository name cannot hold a space and nobody should have to
    work that out twice."""
    from pathlib import Path as P

    page = (P("web/src/pages/NewProjectPage.tsx")).read_text(encoding="utf-8")
    assert "slugify(name)" in page, "the repository name follows the project's"
    assert "touchedRepoName" in page, "typing your own name must win"
    slug = (P("web/src/slug.ts")).read_text(encoding="utf-8")
    # the same folding as the server's, so a branch and a repository agree on Turkish
    for ch in ("ı", "ğ", "ş", "ö", "ç", "ü"):
        assert ch in slug, ch


# --- giving up on a project -----------------------------------------------------------------


def test_a_project_can_be_given_up_on(engine: Engine, client: TestClient, repo: Path) -> None:
    """A development stopped at a gate has no edge to a terminal state, so the ordinary
    delete would refuse this project forever and its worktrees would sit on the disk.
    A purge stops caring about state."""
    from slipwright.schemas.job import JobState

    (repo / "app.py").write_text("x = 1\n")
    project = engine.create_project(Project(name="p", repo_path=repo))
    job = engine.create_job("build a thing", project_id=project.id)
    engine.store.update_state(job.id, JobState.AWAITING_ARCHITECTURE_APPROVAL)
    engine.store.save(engine.workspace.create(engine.store.get(job.id)))
    worktree = engine.store.get(job.id).worktree_path
    assert worktree is not None and worktree.is_dir()

    # the ordinary delete says why it will not
    refused = client.delete(f"/api/projects/{project.id}")
    assert refused.status_code == 409 and "unfinished" in refused.json()["detail"]

    gone = client.delete(f"/api/projects/{project.id}?purge=true")
    assert gone.status_code == 204
    assert client.get(f"/api/projects/{project.id}").status_code == 404
    assert not worktree.exists(), "the worktree was left on the disk"
    # the person's own checkout is not ours to delete
    assert repo.is_dir() and (repo / "app.py").exists()


def test_a_purge_removes_only_a_checkout_we_cloned(
    engine: Engine, client: TestClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The folder under ``repos_root`` is one Slipwright made and is its to remove; a
    folder the person pointed at is their work, and the two must never be confused."""
    import shutil

    def fake_clone(url: str, target: Path) -> None:
        shutil.copytree(repo, target)

    monkeypatch.setattr("slipwright.engine.g.clone", fake_clone)
    made = engine.create_project(Project(name="cloned", github_repo="ada/thing"))
    assert made.repo_path is not None and made.repo_path.parent == engine.repos_root
    checkout = made.repo_path
    assert checkout.is_dir()

    assert client.delete(f"/api/projects/{made.id}?purge=true").status_code == 204
    assert not checkout.exists(), "a checkout we cloned is ours to remove"


def test_a_project_whose_work_is_still_on_a_branch_is_read_not_interviewed(
    engine: Engine, client: TestClient, tmp_path: Path
) -> None:
    """A project opened from an empty repository keeps only the seeded README on main:
    a development works in a worktree of its own and nothing merges it for you. Asked
    about such a project after its agents had written a whole application, this said the
    repository was empty and offered to interview the person about a product that
    already existed."""
    from slipwright.schemas.job import JobState

    project = engine.create_project(Project(name="noteapp", repo_path=_empty_repo(tmp_path)))
    assert client.get(f"/api/projects/{project.id}/brief").json()["kind"] == "intake"

    job = engine.create_job("notes app", project_id=project.id)
    engine.store.save(engine.workspace.create(engine.store.get(job.id)))
    worktree = engine.store.get(job.id).worktree_path
    assert worktree is not None
    (worktree / "app.py").write_text("from fastapi import FastAPI\n")
    engine.store.update_state(job.id, JobState.BACKLOG)

    # the code exists, so there is something to read and nothing to ask
    assert client.get(f"/api/projects/{project.id}/brief").json()["kind"] == "analysis"
    assert engine.brief_source(engine.store.get_project(project.id)) == worktree

    engine.execute_analysis(project.id)
    brief = engine.brief(project.id)
    assert brief.state is BriefState.PROPOSED and brief.items
