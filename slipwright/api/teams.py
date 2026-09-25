"""The team over HTTP: invitations, who is on which agent, and leaving one.

Three audiences, and the module is laid out in that order. A stranger holding a link (the
invitation endpoints are public -- the whole point is that there is no account to log in
with yet), the owner of an account managing their agents, and a member asking what they
themselves may do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from slipwright.api.auth import current_user, require_owner, start_session
from slipwright.auth import InvalidEmail, User, WeakPassword
from slipwright.schemas.profile import RoleName
from slipwright.store import JobStore
from slipwright.teams import InviteRefused, Membership, MemberStatus

if TYPE_CHECKING:
    from slipwright.engine import Engine

router = APIRouter(tags=["teams"])


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def _store(request: Request) -> JobStore:
    store: JobStore = request.app.state.engine.raw_store
    return store


class Invite(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=64, description="What to call them in the list.")
    lang: str = Field(default="tr", description="Which language to write the letter in.")


class TokenOnly(BaseModel):
    token: str = Field(min_length=1)


class AcceptInvitation(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=1)
    name: str = Field(default="", max_length=64)


class InvitationView(BaseModel):
    """What the page behind a link shows before anybody types anything."""

    model_config = ConfigDict(extra="forbid")

    email: str
    name: str
    inviter: str = Field(description="Who sent it, by display name.")
    agents: list[RoleName] = Field(description="The agents this link puts them on.")


class MyTeam(BaseModel):
    """What the signed-in person may do, as the application needs to know it."""

    model_config = ConfigDict(extra="forbid")

    is_member: bool = Field(description="On somebody else's team rather than owning one.")
    agents: list[RoleName] = Field(description="The agents this person acts as, now.")
    memberships: list[Membership] = Field(default_factory=list)


# -- the invitation ------------------------------------------------------------------------


@router.post("/auth/invitation", response_model=InvitationView)
def read_invitation(body: TokenOnly, request: Request) -> InvitationView:
    """Open a link without spending it. 400 once it has been answered or has expired."""
    found = _engine(request).teams().invitation(body.token)
    if found is None:
        raise HTTPException(status_code=400, detail="this invitation is no longer valid")
    user, pending = found
    store = _store(request)
    inviter = ""
    owner_id = pending[0].owner_id
    try:
        inviter = store.get_user(owner_id).username
    except KeyError:  # the account that invited them is gone; the link still says who for
        inviter = ""
    return InvitationView(
        email=user.email or "",
        name=user.username,
        inviter=inviter,
        agents=[m.role for m in pending],
    )


@router.post("/auth/accept-invitation", response_model=User)
def accept_invitation(body: AcceptInvitation, request: Request, response: Response) -> User:
    """Take it: set a password, prove the address and start working, in one call."""
    try:
        user = _engine(request).teams().accept(body.token, body.password, name=body.name)
    except WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=400, detail="this invitation is no longer valid")
    start_session(_store(request), user, request, response)
    return user


@router.post("/auth/decline-invitation", status_code=204)
def decline_invitation(body: TokenOnly, request: Request) -> None:
    """Answer "no". The link is spent either way, so nobody can change their mind for
    them afterwards; the owner can always invite again."""
    if _engine(request).teams().decline(body.token) is None:
        raise HTTPException(status_code=400, detail="this invitation is no longer valid")


# -- the owner's team ------------------------------------------------------------------------


def _visible_to(user: User, store: JobStore, role: RoleName) -> bool:
    """An owner sees every agent's people; a member sees the agents they are on."""
    return not user.is_member or role in store.agents_of(user.id)


@router.get("/agents/{role}/members", response_model=list[Membership])
def list_agent_members(role: RoleName, request: Request) -> list[Membership]:
    """Who is on this agent, including the invitations nobody has answered yet."""
    user = current_user(request)
    store = _store(request)
    if not _visible_to(user, store, role):
        raise HTTPException(status_code=403, detail="this is not one of your agents")
    return store.list_members(user.tenant_id, role=role)


@router.post("/agents/{role}/members", response_model=Membership, status_code=201)
def invite_to_agent(role: RoleName, body: Invite, request: Request) -> Membership:
    """Put somebody on this agent and mail them the invitation."""
    owner = require_owner(request)
    try:
        membership, _secret = (
            _engine(request)
            .teams()
            .invite(owner, role, body.email, lang=body.lang, label=body.name)
        )
    except InvalidEmail as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InviteRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return membership


class TeamInvite(Invite):
    roles: list[RoleName] = Field(min_length=1, description="Which agents to put them on.")


@router.post("/team/members", response_model=list[Membership], status_code=201)
def invite_to_agents(body: TeamInvite, request: Request) -> list[Membership]:
    """Put somebody on several agents at once, with one letter between them all.

    The same act as inviting them to one agent, said once: a person asked onto three
    agents should answer one invitation, not three.
    """
    owner = require_owner(request)
    try:
        memberships, _secret = (
            _engine(request)
            .teams()
            .invite_many(owner, body.roles, body.email, lang=body.lang, label=body.name)
        )
    except InvalidEmail as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InviteRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return memberships


@router.delete("/agents/{role}/members/{member_id}", response_model=Membership)
def end_membership(role: RoleName, member_id: str, request: Request) -> Membership:
    """Take somebody off an agent, or -- asked by that person -- step off it yourself.

    Either way it is the same row ending; only the word for it differs, and only the
    person taken off is written to. Whoever is left with no agent at all is signed out:
    the next thing their browser asks for says so.
    """
    user = current_user(request)
    store = _store(request)
    membership = store.get_membership(member_id)
    if membership is None or membership.role is not role or membership.owner_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="no such membership")
    if not membership.open:
        raise HTTPException(status_code=409, detail="this membership has already ended")
    teams = _engine(request).teams()
    if user.is_member:
        if membership.user_id != user.id:
            raise HTTPException(status_code=403, detail="you may only take yourself off an agent")
        return teams.leave(membership)
    return teams.remove(membership, by=user)


@router.get("/team", response_model=list[Membership])
def list_team(request: Request) -> list[Membership]:
    """Everybody on every agent of this account, for the owner's own list."""
    owner = require_owner(request)
    return _store(request).list_members(owner.id)


# -- what the signed-in person may do ---------------------------------------------------------


@router.get("/me/team", response_model=MyTeam)
def my_team(request: Request) -> MyTeam:
    user = current_user(request)
    store = _store(request)
    if not user.is_member:
        return MyTeam(is_member=False, agents=[], memberships=[])
    mine = store.memberships_of(user.id)
    return MyTeam(
        is_member=True,
        agents=sorted({m.role for m in mine if m.status is MemberStatus.ACTIVE}),
        memberships=mine,
    )


__all__ = ["router"]
