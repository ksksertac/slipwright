"""Login, sessions, users and bearer tokens over HTTP.

``auth_dependency`` is attached to the whole app: every ``/api`` route except login
needs a session cookie or a bearer token; the React shell and its static
assets are public (the app itself shows the login page). When no user exists yet the
API answers 503 with the command that creates the first one.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from slipwright.auth import SESSION_COOKIE, SESSION_TTL, ApiToken, User
from slipwright.store import JobStore, UsernameTaken, UserNotFound

PUBLIC_PATHS = frozenset({"/api/auth/login", "/docs", "/redoc", "/openapi.json", "/healthz"})
NO_USERS_HINT = "no users exist yet; create one with: slipwright user add <name>"


class Credentials(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)
    is_admin: bool = False


class NewPassword(BaseModel):
    password: str = Field(min_length=1)


class NewToken(BaseModel):
    name: str = Field(default="cli", min_length=1)


class IssuedToken(BaseModel):
    token: ApiToken
    secret: str


def _store(request: Request) -> JobStore:
    store: JobStore = request.app.state.engine.store
    return store


def resolve_user(request: Request) -> User | None:
    """The user behind this request: bearer token first, then the session cookie."""
    store = _store(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return store.token_user(header[7:].strip())
    secret = request.cookies.get(SESSION_COOKIE)
    if secret:
        return store.session_user(secret)
    return None


def auth_dependency(*, enabled: bool) -> Callable[[Request], None]:
    """Build the app-wide dependency. Disabled apps (tests) get an anonymous admin."""

    def check(request: Request) -> None:
        if not enabled:
            request.state.user = User(id="anonymous", username="anonymous", is_admin=True)
            return
        path = request.url.path
        protected = path.startswith("/api/")
        if not protected or path in PUBLIC_PATHS:
            request.state.user = None
            return
        store = _store(request)
        if store.count_users() == 0:
            raise HTTPException(status_code=503, detail=NO_USERS_HINT)
        user = resolve_user(request)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.user = user

    return check


def current_user(request: Request) -> User:
    user: User | None = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def require_admin(request: Request) -> User:
    user = current_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return user


router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=User)
def login(body: Credentials, request: Request, response: Response) -> User:
    store = _store(request)
    if store.count_users() == 0:
        raise HTTPException(status_code=503, detail=NO_USERS_HINT)
    user = store.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="wrong username or password")
    secret = store.create_session(user.id)
    response.set_cookie(
        SESSION_COOKIE,
        secret,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    secret = request.cookies.get(SESSION_COOKIE)
    if secret:
        _store(request).delete_session(secret)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=User)
def me(request: Request) -> User:
    return current_user(request)


# -- user administration -------------------------------------------------------------------


@router.get("/users", response_model=list[User])
def list_users(request: Request) -> list[User]:
    require_admin(request)
    return _store(request).list_users()


@router.post("/users", response_model=User, status_code=201)
def create_user(body: NewUser, request: Request) -> User:
    require_admin(request)
    try:
        return _store(request).create_user(body.username, body.password, is_admin=body.is_admin)
    except UsernameTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_user(store: JobStore, user_id: str) -> User:
    try:
        return store.get_user(user_id)
    except UserNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/users/{user_id}/password", status_code=204)
def set_password(user_id: str, body: NewPassword, request: Request) -> None:
    """Admins may reset anyone's password; a user may change their own."""
    me_ = current_user(request)
    if not me_.is_admin and me_.id != user_id:
        raise HTTPException(status_code=403, detail="admin only")
    store = _store(request)
    _get_user(store, user_id)
    store.set_password(user_id, body.password)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, request: Request) -> None:
    me_ = require_admin(request)
    if me_.id == user_id:
        raise HTTPException(status_code=400, detail="you cannot delete yourself")
    store = _store(request)
    _get_user(store, user_id)
    store.delete_user(user_id)


@router.get("/users/{user_id}/tokens", response_model=list[ApiToken])
def list_tokens(user_id: str, request: Request) -> list[ApiToken]:
    me_ = current_user(request)
    if not me_.is_admin and me_.id != user_id:
        raise HTTPException(status_code=403, detail="admin only")
    store = _store(request)
    _get_user(store, user_id)
    return store.list_tokens(user_id)


@router.post("/users/{user_id}/tokens", response_model=IssuedToken, status_code=201)
def create_token(user_id: str, body: NewToken, request: Request) -> IssuedToken:
    """Issue a bearer token. The secret appears in this response only."""
    me_ = current_user(request)
    if not me_.is_admin and me_.id != user_id:
        raise HTTPException(status_code=403, detail="admin only")
    store = _store(request)
    _get_user(store, user_id)
    token, secret = store.create_token(user_id, body.name)
    return IssuedToken(token=token, secret=secret)


@router.delete("/tokens/{token_id}", response_model=ApiToken)
def revoke_token(token_id: str, request: Request) -> ApiToken:
    me_ = current_user(request)
    store = _store(request)
    try:
        token = store.get_token(token_id)
    except UserNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not me_.is_admin and token.user_id != me_.id:
        raise HTTPException(status_code=403, detail="admin only")
    return store.revoke_token(token_id)


__all__ = [
    "PUBLIC_PATHS",
    "Credentials",
    "auth_dependency",
    "current_user",
    "require_admin",
    "resolve_user",
    "router",
]
