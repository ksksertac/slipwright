"""T14.1: a mobile phase names the platform it builds, and is built with that platform's
own commands -- never the project's, which must not need Xcode or an Android SDK."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from slipwright.engine import Engine, InvalidEdit
from slipwright.gates import toolchains
from slipwright.roles.results import ArchitectResult, PlanPhase
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import PlatformCommands, Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import TRUE, full_engine, full_provider

ANDROID_BUILD = TRUE.replace("print(1)", "print('android-built')")


def _with_android(seed: Profile) -> Profile:
    return seed.model_copy(
        update={
            "platforms": [
                PlatformCommands(platform="android", build_cmd=ANDROID_BUILD, test_cmd=TRUE)
            ]
        }
    )


def _drive(engine: Engine, job: Job) -> Job:
    """Approve every gate until the development ends."""
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            return job
        job = engine.approve(job.id)
    raise AssertionError(f"still at {job.state}")


def _plan_with_android_phase(seed: Profile) -> Any:
    provider = full_provider(seed, phases=2, domains=["backend", "mobile"])
    provider.replies[RoleName.ARCHITECT]["phases"][1]["platform"] = "android"
    return provider


# -- the contract ---------------------------------------------------------------------------


def test_only_a_mobile_phase_names_a_platform() -> None:
    assert PlanPhase(goal="app", domain="mobile", platform="ios").platform == "ios"
    assert PlanPhase(goal="shared", domain="mobile").platform is None
    with pytest.raises(ValidationError, match="only a mobile phase"):
        PlanPhase(goal="api", domain="backend", platform="ios")


def test_a_plan_cannot_name_a_platform_nobody_says_how_to_build(seed: Profile) -> None:
    answer = {
        "summary": "plan",
        "profile": seed.model_dump(mode="json"),
        "phases": [
            {
                "goal": "app",
                "task_id": "t1",
                "domain": "mobile",
                "platform": "ios",
                "depends_on": [],
            }
        ],
    }
    with pytest.raises(ValidationError, match="profile.platforms has no commands"):
        ArchitectResult.model_validate(answer)
    answer["profile"]["platforms"] = [{"platform": "ios", "build_cmd": "b", "test_cmd": "t"}]
    assert ArchitectResult.model_validate(answer).phases[0].platform == "ios"


def test_a_platform_is_named_once_and_its_commands_are_its_own(seed: Profile) -> None:
    profile = _with_android(seed)
    assert profile.commands_for("android") == (ANDROID_BUILD, TRUE)
    assert profile.commands_for(None) == (seed.build_cmd, seed.test_cmd)
    twice = profile.model_dump(mode="json")
    twice["platforms"] *= 2
    with pytest.raises(ValidationError, match="each platform once"):
        Profile.model_validate(twice)


# -- what a machine can build -----------------------------------------------------------------


def _sdk(root: Path) -> dict[str, str]:
    (root / "sdk" / "platforms" / "android-35").mkdir(parents=True)
    jdk = root / "jdk"
    jdk.mkdir()
    (jdk / "release").write_text('JAVA_VERSION="21.0.8"\n')
    return {"PATH": "", "ANDROID_HOME": str(root / "sdk"), "JAVA_HOME": str(jdk)}


def test_android_is_built_where_the_sdk_and_a_jdk_are(tmp_path: Path) -> None:
    env = _sdk(tmp_path)
    assert toolchains.can_build("android", env, system="Linux", machine="x86_64")
    assert not toolchains.can_build("android", {"PATH": ""}, system="Linux", machine="x86_64")


def test_android_is_not_built_on_linux_arm64_even_with_an_sdk(tmp_path: Path) -> None:
    """Apple Silicon's Docker: the SDK is there, Google's build-tools for it are not."""
    env = _sdk(tmp_path)
    assert not toolchains.can_build("android", env, system="Linux", machine="aarch64")
    assert toolchains.can_build("android", env, system="Darwin", machine="arm64")


def test_ios_is_built_only_on_macos_with_xcode(tmp_path: Path) -> None:
    assert not toolchains.can_build("ios", {"PATH": ""}, system="Linux", machine="x86_64")
    assert not toolchains.can_build("ios", {"PATH": ""}, system="Darwin", machine="arm64")


# -- the engine -------------------------------------------------------------------------------


def test_a_platform_phase_is_built_with_its_platforms_commands(
    store: JobStore,
    repo: Path,
    worktrees_root: Path,
    seed: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(toolchains, "can_build", lambda platform, *a, **k: True)
    seed = _with_android(seed)
    engine = full_engine(store, worktrees_root, seed, _plan_with_android_phase(seed))
    job = _drive(engine, engine.start(engine.create_job("an app", repo).id))

    assert job.state is JobState.DONE
    passed = {
        t.note: t.detail or ""
        for t in job.history
        if (t.note or "").startswith("build gate passed")
    }
    first = passed["build gate passed for phase 1/2"]
    second = passed["build gate passed for phase 2/2"]
    assert "[build: exit 0]" in first and "android" not in first
    assert "android-built" in second and "[android build: exit 0]" in second
    # QA's gate is the whole project: its own commands, then the app's
    qa = next(t.detail or "" for t in job.history if (t.note or "").startswith("qa: tests"))
    assert "[test: exit 0]" in qa and "[android test: exit 0]" in qa


def test_a_platform_this_machine_cannot_build_is_said_at_the_final_gate(
    store: JobStore,
    repo: Path,
    worktrees_root: Path,
    seed: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _with_android(seed)
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    monkeypatch.setattr(toolchains, "can_build", lambda platform, *a, **k: False)
    job = _drive(engine, engine.start(engine.create_job("an api", repo).id))

    assert job.state is JobState.DONE
    qa = next(t.detail or "" for t in job.history if (t.note or "").startswith("qa: tests"))
    assert "[android: not built here" in qa and "android-built" not in qa


def test_the_gate_editor_keeps_phases_and_their_commands_together(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    seed = _with_android(seed)
    engine = full_engine(store, worktrees_root, seed, _plan_with_android_phase(seed))
    job = engine.start(engine.create_job("an app", repo).id)
    job = engine.approve(job.id)  # the backlog
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert job.profile is not None

    with pytest.raises(InvalidEdit, match="keep their commands"):
        engine.set_profile(job.id, job.profile.model_copy(update={"platforms": []}))

    plan = dict(job.data.plan or {})
    plan["phases"] = [{**p, "platform": "ios"} if p.get("platform") else p for p in plan["phases"]]
    with pytest.raises(InvalidEdit, match="no commands build ios"):
        engine.set_plan(job.id, plan)
