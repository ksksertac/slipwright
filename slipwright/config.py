"""Process configuration: where state lives, which seed profile, which provider.

Everything is overridable through ``SLIPWRIGHT_*`` environment variables so the server
and the CLI need no config file to get going.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from slipwright.engine import Engine
from slipwright.providers import ModelProvider
from slipwright.schemas.profile import Profile, load_profile
from slipwright.secrets import load_or_create_key
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = PACKAGE_ROOT / "examples" / "python-fastapi.profile.json"
_OFF = ("0", "off", "no", "false")


@dataclass
class Settings:
    state_dir: Path = field(default_factory=lambda: Path(".slipwright"))
    profile_path: Path = DEFAULT_PROFILE
    provider: str = "anthropic"
    host: str = "127.0.0.1"
    port: int = 8500
    port_range: tuple[int, int] = (8100, 8999)
    require_auth: bool = True
    token: str | None = None
    dev: bool = False

    @property
    def db_path(self) -> Path:
        return self.state_dir / "jobs.sqlite3"

    @property
    def worktrees_root(self) -> Path:
        return self.state_dir / "worktrees"

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        if env is None:
            env = os.environ
        settings = cls()
        if "SLIPWRIGHT_STATE_DIR" in env:
            settings.state_dir = Path(env["SLIPWRIGHT_STATE_DIR"])
        if "SLIPWRIGHT_PROFILE" in env:
            settings.profile_path = Path(env["SLIPWRIGHT_PROFILE"])
        settings.provider = env.get("SLIPWRIGHT_PROVIDER", settings.provider)
        settings.host = env.get("SLIPWRIGHT_HOST", settings.host)
        settings.port = int(env.get("SLIPWRIGHT_PORT", settings.port))
        if "SLIPWRIGHT_PORT_RANGE" in env:
            lo, hi = env["SLIPWRIGHT_PORT_RANGE"].split("-")
            settings.port_range = (int(lo), int(hi))
        if "SLIPWRIGHT_AUTH" in env:
            settings.require_auth = env["SLIPWRIGHT_AUTH"].strip().lower() not in _OFF
        settings.token = env.get("SLIPWRIGHT_TOKEN") or None
        settings.dev = env.get("SLIPWRIGHT_DEV", "").strip().lower() not in ("", *_OFF)
        return settings


def build_provider(name: str, seed: Profile) -> ModelProvider | None:
    """``None`` means "use the invoke layer's default" (the Anthropic provider)."""
    if name == "anthropic":
        return None
    if name == "scripted":
        from slipwright.providers.scripted import canned

        return canned(seed)
    raise ValueError(f"unknown provider: {name!r} (expected 'anthropic' or 'scripted')")


def build_engine(settings: Settings) -> Engine:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    seed = load_profile(settings.profile_path)
    lo, hi = settings.port_range
    return Engine(
        JobStore(settings.db_path, secret_key=load_or_create_key(settings.state_dir)),
        Workspace(settings.worktrees_root, PortAllocator(start=lo, end=hi)),
        seed_profile=seed,
        provider=build_provider(settings.provider, seed),
    )


__all__ = ["DEFAULT_PROFILE", "Settings", "build_engine", "build_provider"]
