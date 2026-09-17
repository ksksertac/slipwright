"""Docker files stay consistent with each other and with the app (no daemon needed)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_builds_ui_and_ships_the_toolchains() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:" in dockerfile and "npm run build" in dockerfile
    assert "FROM python:3.12" in dockerfile
    for tool in ("git", " gh ", "nodejs", "/uv "):
        assert tool in dockerfile, tool
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "COPY --from=web /src/slipwright/api/static ./slipwright/api/static" in dockerfile
    assert "SLIPWRIGHT_STATE_DIR=/data" in dockerfile and "/healthz" in dockerfile
    assert 'ENTRYPOINT ["slipwright"]' in dockerfile and 'CMD ["serve"]' in dockerfile


def test_compose_maps_ports_state_and_repos() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert '"8500:8500"' in compose
    assert "SLIPWRIGHT_PORT_RANGE" in compose and "8100-8130:8100-8130" in compose
    assert "slipwright-state:/data" in compose and "./repos:/repos" in compose
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "SLIPWRIGHT_SECRET_KEY"):
        assert var in compose, var
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SLIPWRIGHT_SECRET_KEY" in example and "OPENAI_API_KEY" in example
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for path in ("web/node_modules", ".venv", ".git", ".env", "slipwright/api/static"):
        assert path in ignore, path
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/repos/*" in gitignore and ".env" in gitignore
    assert (ROOT / "repos" / ".gitkeep").exists()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docker compose up --build" in readme
