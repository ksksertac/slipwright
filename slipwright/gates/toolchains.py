"""What is already installed where a project's commands run, told to the Architect.

The Architect writes ``build_cmd`` and ``test_cmd`` without ever seeing the machine. Told
only that nothing is installed, it did the reasonable thing for an Android project and
wrote a script that downloads the SDK first -- which then failed three fix rounds running,
because the server runs as an ordinary user with no ``apt-get`` and no ``unzip``. What is
actually there is cheap to find out and worth saying.

Read from the server's own environment. With ``SLIPWRIGHT_RUNNER=docker`` the commands run
in ``Dockerfile.runner`` instead, which is kept carrying the same toolchains as the server
image for exactly this reason. Everything here is a file read: no JVM is started to ask a
version, since the answer is wanted on every plan.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path


def installed(env: Mapping[str, str] | None = None) -> list[str]:
    """One line per toolchain found, empty when there is nothing beyond the basics."""
    source = os.environ if env is None else env
    path = source.get("PATH")
    found: list[str] = []
    java = _java(source.get("JAVA_HOME"))
    if java:
        found.append(java)
    gradle = shutil.which("gradle", path=path)
    if gradle:
        # /opt/gradle/gradle-8.14.3/bin/gradle: the version is in the directory's name
        home = Path(gradle).resolve().parent.parent.name
        named = f"Gradle {home.removeprefix('gradle-')}" if home.startswith("gradle-") else "Gradle"
        found.append(f"{named} as `gradle`")
    android = _android(source.get("ANDROID_HOME") or source.get("ANDROID_SDK_ROOT"))
    if android:
        found.append(android)
    return found


def _java(home: str | None) -> str | None:
    if not home:
        return None
    release = Path(home) / "release"
    try:
        lines = release.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("JAVA_VERSION="):
            return f"JDK {line.split('=', 1)[1].strip().strip(chr(34))} at $JAVA_HOME"
    return None


def _android(home: str | None) -> str | None:
    if not home:
        return None
    root = Path(home)
    platforms = _names(root / "platforms")
    if not platforms:
        return None
    tools = _names(root / "build-tools")
    said = f"Android SDK at $ANDROID_HOME, licences accepted: platforms {', '.join(platforms)}"
    if tools:
        said += f"; build-tools {', '.join(tools)}"
    return said


def _names(folder: Path) -> list[str]:
    try:
        return sorted(p.name for p in folder.iterdir() if p.is_dir())
    except OSError:
        return []


__all__ = ["installed"]
