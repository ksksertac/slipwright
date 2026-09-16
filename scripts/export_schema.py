"""Regenerate schemas/profile.schema.json from the pydantic model.

Run with: uv run python scripts/export_schema.py
A test asserts the committed file matches the model, so run this after changing Profile.
"""

from pathlib import Path

from slipwright.schemas.profile import export_json_schema

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "schemas" / "profile.schema.json"

if __name__ == "__main__":
    export_json_schema(TARGET)
    print(f"wrote {TARGET.relative_to(ROOT)}")
