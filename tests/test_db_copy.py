"""Moving an installation off its SQLite file onto a database server.

The target is the ``store`` fixture, so with ``SLIPWRIGHT_TEST_DATABASE_URL`` set these
copy into a real PostgreSQL -- which is the copy that matters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slipwright.cli import main
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.project import Project
from slipwright.secrets import generate_key
from slipwright.store import JobStore
from slipwright.store.copy import TargetNotEmpty, copy_database
from slipwright.store.db import Database


def _old_installation(path: Path, key: bytes) -> tuple[str, str]:
    """A SQLite installation with somebody in it: returns (project id, job id)."""
    with JobStore(path, secret_key=key) as old:
        ada = old.create_user("ada", "correct horse battery", is_admin=True)
        project = old.create_project(Project(name="Note app", repo_path=Path("/repos/n")))
        project.owner_id = ada.id
        old.update_project(project)
        job = old.create(
            Job.model_validate(
                {"request": "add a health endpoint", "repo_path": Path("/repos/n"),
                 "project_id": project.id, "owner_id": ada.id}
            )
        )
        old.update_state(job.id, JobState.BACKLOG)
        old.update_state(job.id, JobState.AWAITING_BACKLOG_APPROVAL, note="po done")
        old.set_setting("anthropic_api_key", "sk-ant-kept", secret=True, user_id=ada.id)
        return project.id, job.id


def test_an_installation_moved_to_a_server_keeps_its_people_projects_and_keys(
    tmp_path: Path, store: JobStore
) -> None:
    key = generate_key()
    project_id, job_id = _old_installation(tmp_path / "old.sqlite3", key)
    # the server is opened with the key the SQLite file was written with
    store.secret_box = JobStore(tmp_path / "old.sqlite3", secret_key=key).secret_box

    counts = copy_database(Database(tmp_path / "old.sqlite3"), store.db)

    assert counts["users"] == 1 and counts["job_history"] == 2
    ada = store.authenticate("ada", "correct horse battery")
    assert ada is not None and ada.is_admin
    assert [p.name for p in store.list_projects(owner_id=ada.id)] == ["Note app"]
    job = store.get(job_id, owner_id=ada.id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert [t.note for t in job.history] == [None, "po done"]
    assert store.get_setting("anthropic_api_key", user_id=ada.id) == "sk-ant-kept"
    assert store.get_project(project_id).owner_id == ada.id


def test_a_copied_job_carries_on_without_colliding_with_its_own_history(
    tmp_path: Path, store: JobStore
) -> None:
    _, job_id = _old_installation(tmp_path / "old.sqlite3", generate_key())
    copy_database(Database(tmp_path / "old.sqlite3"), store.db)

    # on PostgreSQL the history's sequence had to be moved past the copied rows
    store.update_state(job_id, JobState.ARCHITECTURE, note="approved")

    assert [t.to_state for t in store.get(job_id).history][-1] is JobState.ARCHITECTURE


def test_a_database_that_already_has_accounts_is_not_copied_into(
    tmp_path: Path, store: JobStore
) -> None:
    _old_installation(tmp_path / "old.sqlite3", generate_key())
    store.create_user("grace", "another long password")

    with pytest.raises(TargetNotEmpty):
        copy_database(Database(tmp_path / "old.sqlite3"), store.db)

    assert [u.username for u in store.list_users()] == ["grace"]


def test_the_cli_adds_a_login_to_the_database_the_server_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = tmp_path / "server.sqlite3"
    monkeypatch.setenv("SLIPWRIGHT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SLIPWRIGHT_DATABASE_URL", f"sqlite:///{server.as_posix()}")

    assert main(["user", "add", "ada", "--password", "correct horse battery"]) == 0

    with JobStore(server) as s:
        assert [u.username for u in s.list_users()] == ["ada"]
    # and not to a SQLite file beside the state directory that nothing reads
    assert not (tmp_path / "state" / "jobs.sqlite3").exists()


def test_the_cli_copies_the_state_dirs_sqlite_file_into_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    key = generate_key()
    (state / "secret.key").write_bytes(key + b"\n")
    _old_installation(state / "jobs.sqlite3", key)
    server = tmp_path / "server.sqlite3"
    monkeypatch.setenv("SLIPWRIGHT_STATE_DIR", str(state))
    monkeypatch.setenv("SLIPWRIGHT_DATABASE_URL", f"sqlite:///{server.as_posix()}")

    assert main(["db", "copy"]) == 0

    assert "copied" in capsys.readouterr().out
    with JobStore(server, secret_key=key) as s:
        assert [u.username for u in s.list_users()] == ["ada"]
    # a second run finds the accounts already there and stops
    assert main(["db", "copy"]) == 1
