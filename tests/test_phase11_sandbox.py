"""T11 — what a project's own commands can and cannot reach.

``build_cmd`` and ``test_cmd`` are written by a model and then executed. On a server that
strangers sign up to, that is somebody else's shell on your machine, and these are the
tests that say how far it gets.

Three things must hold, and each of them used to be false:

1. The command's environment carries no secret. It was the server's whole environment
   minus six names, so every provider key, the Git token and the Fernet key that
   decrypts all of them came through.
2. The worktree is not next to the state directory. It was, so ``cat ../../secret.key``
   reached the key from the working directory of every job.
3. A role without ``run_commands`` does not get its build run. The permission was
   declared and never checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slipwright.config import Settings
from slipwright.gates import build_gate, project_env, run_command
from slipwright.gates.env import ALLOWED, leaks
from slipwright.gates.runner import (
    DockerRunner,
    Limits,
    LocalRunner,
    build_runner,
)
from slipwright.schemas.profile import Permission, Profile

# --- the environment -------------------------------------------------------------------------


def test_only_named_variables_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("WHATEVER_ELSE", "also-secret")
    env = project_env()
    assert set(env) <= set(ALLOWED) | {"CI"}
    assert leaks(env, ["sk-secret", "also-secret"]) == []


def test_a_command_really_cannot_read_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not the theory -- the actual subprocess."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-appear")
    monkeypatch.setenv("SLIPWRIGHT_SECRET_KEY", "fernet-should-not-appear")
    probe = (
        "import os; print("
        "os.environ.get('ANTHROPIC_API_KEY', 'unset'), "
        "os.environ.get('SLIPWRIGHT_SECRET_KEY', 'unset'))"
    )
    import sys

    code, out = run_command(f'"{sys.executable}" -c "{probe}"', tmp_path)
    assert code == 0
    assert "should-not-appear" not in out
    assert out.strip() == "unset unset"


# --- where the work happens -------------------------------------------------------------------


def test_the_worktrees_are_not_beside_the_key() -> None:
    """A relative path out of a worktree must not land on the state directory."""
    settings = Settings.from_env({"SLIPWRIGHT_STATE_DIR": "/srv/state"})
    state = settings.state_dir.resolve()
    work = settings.work_dir.resolve()
    assert settings.db_path.resolve().is_relative_to(state)
    assert not work.is_relative_to(state), "a job's commands work inside the state directory"
    assert not state.is_relative_to(work), "the key is reachable from a job's working directory"
    assert settings.worktrees_root.resolve().is_relative_to(work)


def test_the_work_directory_can_be_placed_anywhere() -> None:
    settings = Settings.from_env(
        {"SLIPWRIGHT_STATE_DIR": "/srv/state", "SLIPWRIGHT_WORK_DIR": "/mnt/scratch"}
    )
    assert settings.worktrees_root == Path("/mnt/scratch") / "worktrees"


# --- the permission that was never checked ------------------------------------------------------


def test_a_role_without_run_commands_does_not_get_a_build(
    store: object, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    from tests.pipeline import full_engine, full_provider

    stripped = seed.model_copy(
        update={
            "roles": {
                name: (
                    cfg.model_copy(
                        update={
                            "permissions": [
                                p for p in cfg.permissions if p is not Permission.RUN_COMMANDS
                            ]
                        }
                    )
                )
                for name, cfg in seed.roles.items()
            }
        }
    )
    engine = full_engine(  # type: ignore[arg-type]
        store, worktrees_root, stripped, full_provider(stripped, phases=1)
    )
    job = engine.create_job("x", repo)
    # the gate needs a worktree and the approved profile the architect would have left
    engine.store.save(
        job.model_copy(update={"worktree_path": repo, "profile": stripped})
    )
    gate = engine._run_gate(engine.store.get(job.id))  # noqa: SLF001 - the unit under test
    assert not gate.ok
    assert "run_commands" in gate.output


# --- choosing a runner ---------------------------------------------------------------------------


def test_the_runner_is_chosen_explicitly() -> None:
    assert isinstance(build_runner(env={}), LocalRunner)
    assert isinstance(build_runner(env={"SLIPWRIGHT_RUNNER": "local"}), LocalRunner)
    assert isinstance(build_runner(env={"SLIPWRIGHT_RUNNER": "docker"}), DockerRunner)
    # never a silent fallback: an installation must not believe it is isolated when it
    # asked for something that does not exist
    with pytest.raises(ValueError, match="unknown runner"):
        build_runner(env={"SLIPWRIGHT_RUNNER": "chroot"})


def test_the_container_is_given_nothing_it_does_not_need(tmp_path: Path) -> None:
    runner = DockerRunner(limits=Limits(memory="512m", cpus="1", pids=64, image="img:test"))
    argv = runner._argv("pytest -q", tmp_path, {"PORT": "8123"})  # noqa: SLF001

    joined = " ".join(argv)
    for expected in (
        "--rm",
        "--network=none",
        "--memory=512m",
        "--cpus=1",
        "--pids-limit=64",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
    ):
        assert expected in joined, f"the container is missing {expected}"
    assert "--user=1000:1000" in joined, "the command must not run as root"

    # exactly one mount, and it is the worktree
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert len(mounts) == 1
    assert mounts[0].startswith(str(tmp_path.resolve()))

    # and the only variables inside are the ones this run needs
    passed = dict(
        argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-e"
    )
    assert passed == {"CI": "1", "HOME": "/work", "LANG": "C.UTF-8", "PORT": "8123"}
    # the command itself is the last argument, run by the image's shell
    assert argv[-4:] == ["img:test", "sh", "-lc", "pytest -q"]


def test_a_missing_docker_fails_loudly_rather_than_running_on_the_host(tmp_path: Path) -> None:
    runner = DockerRunner(docker="definitely-not-installed-anywhere")
    result = runner.run("echo hello", tmp_path)
    assert result.exit_code != 0
    assert "not on PATH" in result.output
    assert "hello" not in result.output, "it ran the command anyway"


def test_the_gate_uses_the_runner_it_is_given(tmp_path: Path, seed: Profile) -> None:
    calls: list[str] = []

    class Recording:
        def run(self, cmd: str, cwd: Path, **kw: object) -> object:
            calls.append(cmd)
            from slipwright.gates.runner import CommandResult

            return CommandResult(0, "")

    gate = build_gate(seed, tmp_path, runner=Recording())  # type: ignore[arg-type]
    assert gate.ok
    assert calls == [seed.build_cmd, seed.test_cmd]
