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
    provider: str = "live"
    host: str = "127.0.0.1"
    port: int = 8500
    port_range: tuple[int, int] = (8100, 8999)
    require_auth: bool = True
    token: str | None = None
    dev: bool = False
    # a folder whose sub-folders the UI offers as local checkouts (Docker mounts /repos)
    local_repos: Path | None = None
    # Where everything is kept. Empty means the SQLite file under ``state_dir``, which is
    # what a local install wants; a hosted one points this at its server, e.g.
    # ``postgresql+psycopg://slipwright:…@db/slipwright``.
    database_url: str | None = None
    # Where a job's own commands work: checkouts, clones, logs. Kept apart from the
    # state directory on purpose -- see `work_dir`.
    work_root: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.state_dir / "jobs.sqlite3"

    @property
    def database(self) -> str | Path:
        """What the store opens: the configured URL, else the local SQLite file."""
        return self.database_url or self.db_path

    @property
    def worktrees_root(self) -> Path:
        """Where a job's checkout lives while it is being worked on.

        Deliberately *outside* the state directory. A job's commands run with this as
        their working directory, and those commands are written by a model: while the
        worktrees sat under ``state_dir`` they were one ``../..`` away from
        ``secret.key`` -- the key that decrypts every stored credential -- and from the
        job database beside it. Moving them out does not make the commands safe, but it
        means the one thing that must never be read is not within reach of a relative
        path.
        """
        return self.work_dir / "worktrees"

    @property
    def work_dir(self) -> Path:
        """The tree a job's own commands may touch: checkouts, clones, run logs. Never
        the state directory, which holds the database and the encryption key."""
        return self.work_root or (self.state_dir.parent / f"{self.state_dir.name}-work")

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
        settings.database_url = env.get("SLIPWRIGHT_DATABASE_URL") or None
        if env.get("SLIPWRIGHT_WORK_DIR"):
            settings.work_root = Path(env["SLIPWRIGHT_WORK_DIR"])
        if env.get("SLIPWRIGHT_LOCAL_REPOS"):
            settings.local_repos = Path(env["SLIPWRIGHT_LOCAL_REPOS"])
        settings.dev = env.get("SLIPWRIGHT_DEV", "").strip().lower() not in ("", *_OFF)
        return settings


def build_provider(name: str, seed: Profile) -> ModelProvider | None:
    """``None`` means "route per role" (Anthropic, OpenAI or DeepSeek from the profile,
    keys from Settings → Models or the environment). ``anthropic`` is kept as an alias."""
    if name in ("live", "anthropic"):
        return None
    if name == "scripted":
        from slipwright.providers.scripted import canned

        return canned(seed)
    raise ValueError(f"unknown provider: {name!r} (expected 'live' or 'scripted')")


def build_engine(settings: Settings) -> Engine:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    seed = load_profile(settings.profile_path)
    lo, hi = settings.port_range
    # the key still lives beside the state directory even when the database is elsewhere:
    # a server sets SLIPWRIGHT_SECRET_KEY instead and `load_or_create_key` returns it
    engine = Engine(
        JobStore(settings.database, secret_key=load_or_create_key(settings.state_dir)),
        Workspace(settings.worktrees_root, PortAllocator(start=lo, end=hi)),
        seed_profile=seed,
        provider=build_provider(settings.provider, seed),
    )
    engine.local_repos_root = settings.local_repos
    return engine


__all__ = ["DEFAULT_PROFILE", "Settings", "build_engine", "build_provider"]
