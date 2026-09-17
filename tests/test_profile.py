import json
from pathlib import Path
from typing import Any

import pytest

from slipwright.schemas.profile import (
    Permission,
    Profile,
    ProfileValidationError,
    RoleName,
    ThinkingDepth,
    load_profile,
    parse_profile,
    profile_json_schema,
)

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"
SCHEMA_FILE = ROOT / "schemas" / "profile.schema.json"


def _valid_data() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_example_profile_loads() -> None:
    profile = load_profile(EXAMPLE)
    assert profile.language == "python"
    assert set(profile.roles) == set(RoleName)
    assert profile.roles[RoleName.DEVOPS].thinking_depth is ThinkingDepth.OFF
    assert Permission.GIT_PUSH in profile.roles[RoleName.DEVOPS].permissions


def test_round_trip_json() -> None:
    profile = load_profile(EXAMPLE)
    dumped = profile.model_dump_json()
    assert Profile.model_validate_json(dumped) == profile


def test_committed_json_schema_matches_model() -> None:
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert committed == profile_json_schema(), (
        "schemas/profile.schema.json is stale; run `uv run python scripts/export_schema.py`"
    )


def test_example_validates_against_exported_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(_valid_data(), profile_json_schema())


def test_missing_role_is_readable_error() -> None:
    data = _valid_data()
    del data["roles"]["devops"]
    with pytest.raises(ProfileValidationError) as excinfo:
        parse_profile(data)
    message = str(excinfo.value)
    assert "roles" in message
    assert "devops" in message


def test_unknown_role_rejected() -> None:
    data = _valid_data()
    data["roles"]["intern"] = data["roles"]["qa"]
    with pytest.raises(ProfileValidationError) as excinfo:
        parse_profile(data)
    assert "roles.intern" in str(excinfo.value)


def test_run_cmd_requires_port_placeholder() -> None:
    data = _valid_data()
    data["run_cmd"] = "uv run uvicorn app.main:app"
    with pytest.raises(ProfileValidationError) as excinfo:
        parse_profile(data)
    assert "run_cmd" in str(excinfo.value)
    assert "{port}" in str(excinfo.value)


def test_multiple_errors_are_all_reported() -> None:
    data = _valid_data()
    data["port"] = 80
    data["roles"]["qa"]["thinking_depth"] = "galaxy-brain"
    data["roles"]["qa"]["permissions"] = ["read_files", "read_files"]
    with pytest.raises(ProfileValidationError) as excinfo:
        parse_profile(data)
    message = str(excinfo.value)
    assert "3 error(s)" in message
    assert "port" in message
    assert "roles.qa.thinking_depth" in message
    assert "roles.qa.permissions" in message
    assert len(excinfo.value.errors) == 3


def test_extra_fields_rejected() -> None:
    data = _valid_data()
    data["colour"] = "blue"
    with pytest.raises(ProfileValidationError) as excinfo:
        parse_profile(data)
    assert "colour" in str(excinfo.value)


def test_invalid_json_file_is_readable_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileValidationError) as excinfo:
        load_profile(broken)
    assert "not valid JSON" in str(excinfo.value)
