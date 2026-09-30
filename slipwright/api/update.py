"""The version corner: which release this is, whether a newer one is out, and the press
that installs it.

Anybody signed in sees it and may press it. What a press can do is narrow on purpose: it
installs the release the registry has already offered -- never an image named in the
request -- and only one that is newer than what runs. The worst a stranger on a shared
server can do with it is the update its owner would have done anyway, a little earlier.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.job import TERMINAL_STATES
from slipwright.update import Updater, UpdateRefused

router = APIRouter(tags=["update"])


class UpdateStatus(BaseModel):
    current: str = Field(description="The release this server runs.")
    latest: str | None = Field(
        default=None, description="A newer release, when there is one; otherwise null."
    )
    notes_url: str | None = Field(default=None, description="What the newer release changes.")
    can_install: bool = Field(description="Whether the button can install it by itself.")
    blocked: Literal["no_docker", "source"] | None = Field(
        default=None,
        description="Why it cannot: no_docker -- the Docker socket is not mounted; "
        "source -- the server is not running in a container.",
    )
    command: str = Field(description="What to run instead, when it cannot.")
    state: Literal["idle", "pulling", "restarting", "failed"] = "idle"
    error: str | None = None
    backup: bool = Field(description="Whether the database is copied before installing.")
    running_jobs: int = Field(
        description="Developments in flight on the whole server. They carry on after the "
        "restart, from the step they were on."
    )


class UpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=40)


def _updater(request: Request) -> Updater:
    updater: Updater = request.app.state.updater
    return updater


def _status(request: Request) -> UpdateStatus:
    status = _updater(request).status()
    # the whole server's, not the caller's: a restart interrupts everybody's work, and
    # the count is all that is said about it
    jobs = request.app.state.engine.raw_store.list()
    return UpdateStatus(
        current=status.current,
        latest=status.latest,
        notes_url=status.notes_url,
        can_install=status.blocked is None,
        blocked=status.blocked,
        command=status.command,
        state=status.state,
        error=status.error,
        backup=status.backup,
        running_jobs=sum(1 for j in jobs if j.state not in TERMINAL_STATES),
    )


@router.get("/update", response_model=UpdateStatus)
def get_update(request: Request) -> UpdateStatus:
    """What runs and what is out. Cheap: the registry is asked in the background, not
    here, so every open page may ask this as often as it likes."""
    return _status(request)


@router.post("/update", response_model=UpdateStatus, status_code=202)
def install_update(body: UpdateIn, request: Request) -> UpdateStatus:
    """Install the release on offer. Answers at once; the server restarts on the new
    version shortly after, and the page notices it has."""
    try:
        _updater(request).install(body.version)
    except UpdateRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _status(request)


__all__ = ["UpdateIn", "UpdateStatus", "router"]
