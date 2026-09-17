from __future__ import annotations

from pathlib import Path

import pytest

from slipwright.schemas.profile import load_profile, Profile, RoleName, RoleConfig, ThinkingDepth, Permission
from slipwright.orchestrator import Orchestrator
from slipwright.store import JobStore
from slipwright import invoke


def _example_profile() -> Profile:
    p = load_profile(Path(__file__).resolve().parent.parent / "examples" / "python-fastapi.profile.json")
    return p


def test_invoke_role_honors_profile(tmp_path: Path) -> None:
    profile = _example_profile()

    # call invoke_role for analyst and expect a RoleResult-like dict
    res = invoke.invoke_role(RoleName.ANALYST, profile, {"repo": "/repo"})

    assert isinstance(res, dict)
    assert "result" in res
    assert "summary" in res


def test_invoke_role_invalid_role_raises(tmp_path: Path) -> None:
    profile = _example_profile()

    with pytest.raises(KeyError):
        invoke.invoke_role("bogus-role", profile, {})
