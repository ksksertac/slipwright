"""Docker files stay consistent with each other and with the app (no daemon needed)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_builds_ui_and_ships_the_toolchains() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    # the UI stage runs on the build machine's own platform, so it may carry --platform
    assert "node:22-bookworm-slim AS web" in dockerfile and "npm run build" in dockerfile
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
    assert "slipwright-state:/data" in compose and "${SLIPWRIGHT_REPOS:-./repos}:/repos" in compose
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


def test_the_runner_image_carries_the_same_android_toolchain_as_the_server() -> None:
    """The Architect is told what the server has; with the container runner the commands
    run in the other image, so the two must not drift apart."""
    server = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runner = (ROOT / "Dockerfile.runner").read_text(encoding="utf-8")

    def pinned(text: str) -> list[str]:
        prefixes = ("ARG ANDROID_", "ARG GRADLE_")
        return sorted(line for line in text.splitlines() if line.startswith(prefixes))

    assert pinned(server) == pinned(runner)
    assert any(line.startswith("ARG ANDROID_PACKAGES=") for line in pinned(server))
    # a React Native app's Android build compiles native code: without these it stops
    # before Gradle starts, and nothing a project's commands may do can install them
    packages = next(line for line in pinned(server) if line.startswith("ARG ANDROID_PACKAGES="))
    assert "ndk;" in packages and "cmake;" in packages
    for text in (server, runner):
        assert "ANDROID_HOME=/opt/android-sdk" in text and "JAVA_HOME=/opt/java/openjdk" in text
        assert "/usr/local/bin/gradle" in text
