"""What the Architect is told is installed where a project's commands run."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from slipwright.gates import project_env, toolchains


def _sdk(root: Path) -> Path:
    for folder in ("platforms/android-35", "platforms/android-36", "build-tools/35.0.0"):
        (root / folder).mkdir(parents=True)
    return root


def _jdk(root: Path) -> Path:
    root.mkdir()
    (root / "release").write_text('IMPLEMENTOR="Eclipse Adoptium"\nJAVA_VERSION="21.0.8"\n')
    return root


def test_an_android_sdk_and_a_jdk_are_named_with_what_they_hold(tmp_path: Path) -> None:
    env = {
        "PATH": "",
        "ANDROID_HOME": str(_sdk(tmp_path / "sdk")),
        "JAVA_HOME": str(_jdk(tmp_path / "jdk")),
    }
    said = toolchains.installed(env)
    assert "JDK 21.0.8 at $JAVA_HOME" in said
    android = next(line for line in said if line.startswith("Android SDK"))
    assert "android-35, android-36" in android and "build-tools 35.0.0" in android


@pytest.mark.skipif(sys.platform == "win32", reason="a shell script is not a Windows command")
def test_gradle_is_named_with_its_version(tmp_path: Path) -> None:
    home = tmp_path / "gradle-8.14.3" / "bin"
    home.mkdir(parents=True)
    (home / "gradle").write_text("#!/bin/sh\n")
    (home / "gradle").chmod(0o755)
    assert toolchains.installed({"PATH": str(home)}) == ["Gradle 8.14.3 as `gradle`"]


def test_a_machine_without_them_says_nothing(tmp_path: Path) -> None:
    # an ANDROID_HOME that points at nothing is not an SDK
    assert toolchains.installed({"PATH": "", "ANDROID_HOME": str(tmp_path / "gone")}) == []


def test_the_build_commands_can_find_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANDROID_HOME", "/opt/android-sdk")
    monkeypatch.setenv("JAVA_HOME", "/opt/java/openjdk")
    env = project_env()
    assert env["ANDROID_HOME"] == "/opt/android-sdk"
    assert env["JAVA_HOME"] == "/opt/java/openjdk"
