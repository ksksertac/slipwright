"""Regenerate the committed schema files from the code.

- schemas/profile.schema.json  from the Profile pydantic model
- schemas/openapi.json         from the FastAPI app (the web UI's client is generated from it)

Run with: uv run python scripts/export_schema.py
Tests assert the committed files match, so run this after changing models or routes.
"""

import json
from pathlib import Path

from slipwright.api import openapi_schema
from slipwright.schemas.profile import export_json_schema

ROOT = Path(__file__).resolve().parent.parent
PROFILE_TARGET = ROOT / "schemas" / "profile.schema.json"
OPENAPI_TARGET = ROOT / "schemas" / "openapi.json"


def export_openapi(path: Path) -> None:
    # LF on every platform: the generated client carries a hash of these bytes and the
    # repository stores the file with LF (.gitattributes), so a CRLF copy would make the
    # committed pair disagree on a fresh checkout.
    text = json.dumps(openapi_schema(), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    export_json_schema(PROFILE_TARGET)
    print(f"wrote {PROFILE_TARGET.relative_to(ROOT)}")
    export_openapi(OPENAPI_TARGET)
    print(f"wrote {OPENAPI_TARGET.relative_to(ROOT)}")
