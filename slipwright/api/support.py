"""The support desk over HTTP.

Anybody signed in may write a request -- including somebody whose address is not yet
confirmed, because "the verification letter never arrived" is exactly the thing a support
page exists to hear. Reading other people's requests is admin-only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from slipwright.api.auth import current_user, require_admin
from slipwright.engine import Engine
from slipwright.store import SupportRequestNotFound
from slipwright.support import CATEGORIES, SupportError, TooManyRequests

router = APIRouter(tags=["support"])

Category = Literal["question", "problem", "billing", "feature", "other"]


class SupportRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=10_000)
    category: Category = "question"
    email: str | None = Field(
        default=None,
        max_length=320,
        description="Where to answer. Defaults to the address on the account.",
    )
    lang: Literal["tr", "en"] = "tr"


class SupportRequestView(BaseModel):
    id: str
    user_id: str | None = None
    name: str = ""
    email: str
    category: str
    subject: str
    message: str
    delivery: str = Field(description="sent | outbox | failed — where the letter ended up.")
    delivery_error: str | None = None
    sent_to: str | None = None
    status: str = "open"
    created_at: datetime
    closed_at: datetime | None = None


class SupportStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "closed"]


def _engine(request: Request) -> Engine:
    eng: Engine = request.app.state.engine
    return eng


@router.post("/support", response_model=SupportRequestView, status_code=201)
def create_support_request(body: SupportRequestIn, request: Request) -> SupportRequestView:
    """Write a support request. It is saved first and posted second, so the answer is
    owed even when the mail server is down; ``delivery`` says which happened."""
    user = current_user(request)
    address = (body.email or user.email or "").strip()
    if not address:
        raise HTTPException(
            status_code=400,
            detail="this account has no email address; give one to be answered at",
        )
    try:
        row = _engine(request).support().submit(
            email=address,
            subject=body.subject,
            message=body.message,
            user_id=str(user.id),
            name=user.username,
            category=body.category,
            lang=body.lang,
        )
    except TooManyRequests as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except SupportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SupportRequestView(**row)


@router.get("/support/mine", response_model=list[SupportRequestView])
def list_my_support_requests(request: Request, limit: int = 50) -> list[SupportRequestView]:
    """What this account has written, newest first."""
    user = current_user(request)
    store = _engine(request).store
    return [
        SupportRequestView(**row)
        for row in store.list_support_requests(user_id=str(user.id), limit=limit)
    ]


@router.get("/support", response_model=list[SupportRequestView])
def list_support_requests(request: Request, limit: int = 100) -> list[SupportRequestView]:
    """Every request anybody has written. Admin-only: they carry other people's words."""
    require_admin(request)
    store = _engine(request).store
    return [SupportRequestView(**row) for row in store.list_support_requests(limit=limit)]


@router.put("/support/{request_id}/status", response_model=SupportRequestView)
def set_support_status(
    request_id: str, body: SupportStatusIn, request: Request
) -> SupportRequestView:
    """Mark a request handled, or open it again. Nothing closes one on its own."""
    require_admin(request)
    try:
        row = _engine(request).store.set_support_status(request_id, body.status)
    except SupportRequestNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SupportRequestView(**row)


__all__ = ["CATEGORIES", "router"]
