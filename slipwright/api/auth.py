"""Login, sessions, users and bearer tokens over HTTP.

``auth_dependency`` is attached to the whole app: every ``/api`` route except login
needs a session cookie or a bearer token; the React shell and its static
assets are public (the app itself shows the login page). When no user exists yet the
API answers 503 with the command that creates the first one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from slipwright import twofactor
from slipwright.accounts import LOGIN_LIMIT, RESET_LIMIT, WINDOW_S, TooManyAttempts
from slipwright.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    ApiToken,
    InvalidEmail,
    User,
    UserStatus,
    WeakPassword,
    normalise_email,
)
from slipwright.firstrun import NAME as FIRST_RUN_NAME
from slipwright.firstrun import PASSWORD as FIRST_RUN_PASSWORD
from slipwright.firstrun import default_admin_still_open
from slipwright.quota import forget_everything
from slipwright.store import JobStore, UsernameTaken, UserNotFound
from slipwright.store.users import EmailTaken

if TYPE_CHECKING:
    from slipwright.engine import Engine


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def engine_for(request: Request) -> Engine:
    """The engine bound to whoever is asking.

    Model keys, Git and Jira tokens and which model each agent runs on belong to an
    account, so anything that reads or writes them must go through that account's
    settings. This was once done in the settings router and *not* in the projects one:
    the Agents page then read the installation's settings, showed Anthropic as the
    default however the person had set theirs, and pinning an agent to a model wrote
    somewhere no job would ever read.

    Somebody invited onto a team is bound to the account that invited them
    (``tenant_id``), because the settings their work runs under are that account's. What
    they may *change* is decided by the guards on each endpoint, not here.
    """
    engine = _engine(request)
    user = getattr(request.state, "user", None)
    if user is None or user.id == "anonymous":
        return engine
    return engine.for_user(str(user.tenant_id))


#: Told to the browser when a session is refused for a reason worth showing on the login
#: page. The application clears it as soon as it has been read once.
SIGNED_OUT_HEADER = "X-Slipwright-Signed-Out"
#: You were on a team and are on none any more.
SIGNED_OUT_REMOVED = "removed"
#: The invitation was never answered, so there is no account to come in with.
SIGNED_OUT_INVITED = "invited"

#: Said with a 401 when the password was right and a code from the authenticator app is
#: what is still missing (``required``) or what was wrong (``invalid``). The login page
#: reads it to ask for the code, rather than parsing the words.
TWO_FACTOR_HEADER = "X-Slipwright-Two-Factor"

PUBLIC_PATHS = frozenset(
    {
        "/api/auth/login",
        "/api/auth/first-run",
        "/api/auth/invitation",
        "/api/auth/accept-invitation",
        "/api/auth/decline-invitation",
        "/api/auth/signup",
        "/api/auth/verify",
        "/api/auth/resend-verification",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/healthz",
    }
)
#: Paths a chat service, a paired Mac or another installation calls, not a person. Anybody
#: on the internet can reach them, so each one proves the caller itself -- Teams' signed
#: token, in ``api/notify.py``; a connection code or a worker token, in ``api/workers.py``;
#: the key exchange and the parts sealed with its key, in ``api/transfer.py`` -- and
#: refuses before reading anything when that proof is missing.
PUBLIC_PREFIXES = ("/api/notify/inbound/", "/api/worker/", "/api/transfer/peer/")
NO_USERS_HINT = "no users exist yet; create one with: slipwright user add <name>"
#: What every "is this address known?" endpoint says, whatever the answer.
SENT_IF_KNOWN = "if that address has an account, a message is on its way"


class Credentials(BaseModel):
    """``username`` is the login identity: an email address, or for an account made
    before signup existed, the name it was created with."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    code: str | None = Field(
        default=None,
        description="From the authenticator app, or a recovery code; only asked of an "
        "account with two-step sign-in on.",
    )


class SignUp(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)
    name: str = Field(default="", max_length=64, description="Display name; the address if blank.")
    lang: str = Field(default="tr", description="Which language to write the letter in.")


class EmailOnly(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    lang: str = "tr"


class TokenOnly(BaseModel):
    token: str = Field(min_length=1)


class ResetPassword(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=1)


class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)
    email: str | None = None
    is_admin: bool = False


class StatusChange(BaseModel):
    status: UserStatus


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
        if not protected or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
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
        if user.status is UserStatus.REMOVED:
            # the session is still good; the person is not on any agent any more. Saying
            # so here is what puts a browser that is open right now back on the login
            # page with a reason rather than an unexplained 401.
            raise HTTPException(
                status_code=401,
                detail="you are no longer on any agent of this team",
                headers={SIGNED_OUT_HEADER: SIGNED_OUT_REMOVED},
            )
        if user.status is UserStatus.INVITED:
            raise HTTPException(
                status_code=401,
                detail="accept your invitation first",
                headers={SIGNED_OUT_HEADER: SIGNED_OUT_INVITED},
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
    if not user.is_admin or user.is_member:
        raise HTTPException(status_code=403, detail="admin only")
    return user


def require_owner(request: Request) -> User:
    """For everything that belongs to whoever owns the account rather than to an agent.

    Starting and steering developments, creating and deleting projects, the settings and
    the team itself. A member's part is the gates of their own agents; this is the rest.
    """
    user = current_user(request)
    if user.is_member:
        raise HTTPException(
            status_code=403,
            detail="this is for the owner of the account; you are on this team for your agents",
        )
    return user


def require_verified(request: Request) -> User:
    """For the endpoints that start work rather than just show it.

    An unverified account may sign in and look around -- that is how somebody who has
    lost the letter finds the "send it again" button -- but it may not create projects or
    run agents, because that is what a throwaway address would be for.

    Unless nothing can post the letter. An installation with no mail server writes it to
    the outbox instead, which only an administrator can read, so asking somebody to
    confirm an address is a lock whose key is in a drawer they cannot open -- and on a
    machine somebody has just started, there is no stranger to keep out anyway. The proof
    is asked for when it can be given: set a mail server up, and it is asked for again.
    """
    user = current_user(request)
    if not user.active:
        raise HTTPException(status_code=403, detail="this account is suspended")
    if not _engine(request).mail_settings().configured:
        return user
    if not user.verified:
        raise HTTPException(
            status_code=403,
            detail="confirm your email address first; we can send the link again",
        )
    return user


router = APIRouter(tags=["auth"])


class FirstRun(BaseModel):
    """What the login page needs to know before anybody has signed in."""

    model_config = ConfigDict(extra="forbid")

    default_admin: bool = Field(
        description="The starting account is still on its default password, so the login "
        "page can say what it is -- and keep asking for it to be changed."
    )
    username: str = ""
    password: str = ""


@router.get("/auth/first-run", response_model=FirstRun)
def first_run(request: Request) -> FirstRun:
    """Public on purpose: it tells anybody who asks that the default password works.

    That sounds like a leak and is the opposite of one. The password is a published
    default -- announcing it changes nothing for an attacker, who would try it first, and
    changes everything for the person who has just started the server and is looking at a
    login form with nothing to type.
    """
    if not default_admin_still_open(_engine(request).raw_store):
        return FirstRun(default_admin=False)
    return FirstRun(default_admin=True, username=FIRST_RUN_NAME, password=FIRST_RUN_PASSWORD)


def start_session(store: JobStore, user: User, request: Request, response: Response) -> None:
    """Issue the session cookie. Shared by login, signup, verify and reset."""
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


@router.post("/auth/login", response_model=User)
def login(body: Credentials, request: Request, response: Response) -> User:
    store = _store(request)
    if store.count_users() == 0:
        raise HTTPException(status_code=503, detail=NO_USERS_HINT)
    # guessing is rationed per identifier, so one account cannot be ground down
    if store.hit_rate_limit(
        f"login:{body.username.strip().lower()}", limit=LOGIN_LIMIT, window_s=WINDOW_S
    ):
        raise HTTPException(status_code=429, detail="too many attempts; try again later")
    user = store.authenticate(body.username, body.password, allow_inactive=True)
    if user is None:
        raise HTTPException(status_code=401, detail="wrong username or password")
    if user.status is UserStatus.REMOVED:
        raise HTTPException(
            status_code=403,
            detail="you are no longer on any agent of this team",
            headers={SIGNED_OUT_HEADER: SIGNED_OUT_REMOVED},
        )
    if user.status is UserStatus.INVITED:
        raise HTTPException(
            status_code=403,
            detail="accept your invitation first; the link is in the letter we sent you",
            headers={SIGNED_OUT_HEADER: SIGNED_OUT_INVITED},
        )
    if not user.active:
        # a suspended account says exactly what a wrong password says: it was closed by
        # an administrator, and confirming that it exists is not this endpoint's business
        raise HTTPException(status_code=401, detail="wrong username or password")
    if user.two_factor:
        _second_step(store, user, body.code)
    start_session(store, user, request, response)
    return user


def _second_step(store: JobStore, user: User, code: str | None) -> None:
    """Refuse unless ``code`` is good. Only reached once the password was right.

    Stateless on purpose: the browser sends the password again with the code, so there
    is no half-signed-in session to steal or to expire. Codes are rationed per *account*
    as well as per identifier, because somebody who has the password could otherwise
    take turns between the address and the username to double their guesses.
    """
    if not code or not code.strip():
        raise HTTPException(
            status_code=401,
            detail="enter the code from your authenticator app",
            headers={TWO_FACTOR_HEADER: "required"},
        )
    if store.hit_rate_limit(f"2fa:{user.id}", limit=LOGIN_LIMIT, window_s=WINDOW_S):
        raise HTTPException(status_code=429, detail="too many attempts; try again later")
    if not store.check_two_factor(user.id, code):
        raise HTTPException(
            status_code=401,
            detail="that code is not right, or it has been used already",
            headers={TWO_FACTOR_HEADER: "invalid"},
        )


def session_from_link(store: JobStore, user: User, request: Request, response: Response) -> User:
    """A letter's link ends with a session -- unless the account asks for a code.

    A verification or reset link proves the mailbox, not the phone: signing in from one
    would make two-step sign-in exactly as strong as the email account. What the link was
    for has been done by now; the person is sent on to sign in with the second step."""
    if user.two_factor:
        raise HTTPException(
            status_code=401,
            detail="done; now sign in, with the code from your authenticator app",
            headers={TWO_FACTOR_HEADER: "required"},
        )
    start_session(store, user, request, response)
    return user


@router.post("/auth/signup", response_model=User, status_code=201)
def sign_up(body: SignUp, request: Request, response: Response) -> User:
    """Open an account and mail the link that proves the address.

    The session starts straight away: an unverified user can look around while the letter
    is in flight, and only work is refused (see ``require_verified``).
    """
    accounts = _engine(request).accounts()
    try:
        user = accounts.sign_up(body.email, body.password, body.name, lang=body.lang)
    except InvalidEmail as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmailTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    start_session(_store(request), user, request, response)
    return user


@router.post("/auth/verify", response_model=User)
def verify_email(body: TokenOnly, request: Request, response: Response) -> User:
    """Redeem a verification link and sign the person in."""
    user = _engine(request).accounts().verify(body.token)
    if user is None:
        raise HTTPException(status_code=400, detail="this link is no longer valid")
    return session_from_link(_store(request), user, request, response)


@router.post("/auth/resend-verification", status_code=202)
def resend_verification(body: EmailOnly, request: Request) -> dict[str, str]:
    """Send the verification letter again. Says the same thing whoever asks."""
    engine = _engine(request)
    store = _store(request)
    try:
        address = normalise_email(body.email)
    except InvalidEmail:
        return {"detail": SENT_IF_KNOWN}
    if store.hit_rate_limit(f"verify:{address}", limit=RESET_LIMIT, window_s=WINDOW_S):
        return {"detail": SENT_IF_KNOWN}
    user = store.find_by_email(address)
    if user is not None and user.active:
        engine.accounts().send_verification(user, lang=body.lang)
    return {"detail": SENT_IF_KNOWN}


@router.post("/auth/forgot-password", status_code=202)
def forgot_password(body: EmailOnly, request: Request) -> dict[str, str]:
    """Ask for a reset link. Always the same answer: this must not reveal who has an
    account here."""
    _engine(request).accounts().request_reset(body.email, lang=body.lang)
    return {"detail": SENT_IF_KNOWN}


@router.post("/auth/reset-password", response_model=User)
def reset_password(body: ResetPassword, request: Request, response: Response) -> User:
    """Set a new password from a reset link, then sign in with it.

    Every other session and bearer token of that account is dropped by ``set_password``,
    which is the point: somebody who has lost control of the account gets it back.
    """
    try:
        user = _engine(request).accounts().reset_password(body.token, body.password)
    except WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=400, detail="this link is no longer valid")
    return session_from_link(_store(request), user, request, response)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    secret = request.cookies.get(SESSION_COOKIE)
    if secret:
        _store(request).delete_session(secret)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=User)
def me(request: Request) -> User:
    return current_user(request)


# -- two-step sign-in -----------------------------------------------------------------------


class TwoFactorStatus(BaseModel):
    enabled: bool
    recovery_codes_left: int = Field(
        description="Unspent recovery codes; worth a warning when it runs low."
    )


class TwoFactorSetup(BaseModel):
    """What an authenticator app needs: scan ``qr``, or type ``secret`` in by hand."""

    secret: str
    uri: str
    qr: str = Field(description="The QR code, as an SVG data: URI.")


class TwoFactorCode(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class TwoFactorOff(BaseModel):
    password: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=32)


class RecoveryCodes(BaseModel):
    recovery_codes: list[str]


def _person(request: Request) -> User:
    """Somebody signed in as themselves. The anonymous user of an app without logins has
    no account to put a second step on."""
    user = current_user(request)
    if user.id == "anonymous":
        raise HTTPException(status_code=400, detail="there is no account to secure here")
    return user


@router.get("/auth/two-factor", response_model=TwoFactorStatus)
def two_factor_status(request: Request) -> TwoFactorStatus:
    user = _person(request)
    left = _store(request).recovery_codes_left(user.id) if user.two_factor else 0
    return TwoFactorStatus(enabled=user.two_factor, recovery_codes_left=left)


@router.post("/auth/two-factor/setup", response_model=TwoFactorSetup)
def two_factor_setup(request: Request) -> TwoFactorSetup:
    """A new secret to scan. Signing in is unchanged until a code from it comes back."""
    user = _person(request)
    try:
        secret = _store(request).start_two_factor(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    uri = twofactor.provisioning_uri(secret, user.email or user.username)
    return TwoFactorSetup(secret=secret, uri=uri, qr=twofactor.qr_svg(uri))


@router.post("/auth/two-factor/enable", response_model=RecoveryCodes)
def two_factor_enable(body: TwoFactorCode, request: Request) -> RecoveryCodes:
    """Turn it on with a code that proves the app has the secret; returns the recovery
    codes, which are never shown again."""
    user = _person(request)
    store = _store(request)
    if store.hit_rate_limit(f"2fa:{user.id}", limit=LOGIN_LIMIT, window_s=WINDOW_S):
        raise HTTPException(status_code=429, detail="too many attempts; try again later")
    try:
        codes = store.enable_two_factor(user.id, body.code)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if codes is None:
        raise HTTPException(status_code=400, detail="that code is not right; try the next one")
    return RecoveryCodes(recovery_codes=codes)


@router.post("/auth/two-factor/disable", response_model=User)
def two_factor_disable(body: TwoFactorOff, request: Request) -> User:
    """Turn it off. Asks for the password *and* a code: a session left open on a shared
    machine must not be enough to take the second step away."""
    user = _person(request)
    store = _store(request)
    if store.hit_rate_limit(f"2fa:{user.id}", limit=LOGIN_LIMIT, window_s=WINDOW_S):
        raise HTTPException(status_code=429, detail="too many attempts; try again later")
    if not store.check_password(user.id, body.password):
        raise HTTPException(status_code=400, detail="wrong password")
    if not user.two_factor:
        return user
    if not store.check_two_factor(user.id, body.code):
        raise HTTPException(status_code=400, detail="that code is not right")
    return store.disable_two_factor(user.id)


# -- user administration -------------------------------------------------------------------


@router.get("/users", response_model=list[User])
def list_users(request: Request) -> list[User]:
    """The accounts this administrator may see: their own, and the people on their team.

    An installation whose administrator owns nothing (the first user of a local install)
    still sees everybody, which is what it always did.
    """
    user = require_admin(request)
    store = _store(request)
    mine = store.list_users(owner_id=user.id)
    return mine if len(mine) > 1 else store.list_users()


@router.post("/users", response_model=User, status_code=201)
def create_user(body: NewUser, request: Request) -> User:
    require_admin(request)
    try:
        # an account an administrator opens is trusted: there is nobody to mail a link to
        return _store(request).create_user(
            body.username,
            body.password,
            is_admin=body.is_admin,
            email=body.email,
            verified=True,
        )
    except EmailTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@router.delete("/users/{user_id}/two-factor", response_model=User)
def reset_two_factor(user_id: str, request: Request) -> User:
    """An administrator takes the second step off somebody who lost their phone and
    their recovery codes. The only way back in for them short of the database, so it is
    the administrator's -- the same people who may already reset a password."""
    require_admin(request)
    store = _store(request)
    _get_user(store, user_id)
    return store.disable_two_factor(user_id)


@router.put("/users/{user_id}/status", response_model=User)
def set_user_status(user_id: str, body: StatusChange, request: Request) -> User:
    """Suspend an account or let it back in.

    Suspending drops its sessions at once rather than at the next login, and nothing is
    deleted: it is the reversible half of closing an account.
    """
    me_ = require_admin(request)
    if me_.id == user_id:
        raise HTTPException(status_code=400, detail="you cannot suspend yourself")
    store = _store(request)
    _get_user(store, user_id)
    return store.set_status(user_id, body.status)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, request: Request) -> None:
    """Close an account and remove what it left behind.

    Its projects, developments, checkouts, clones, settings and rewritten standards pages
    all go. Somebody asking to be forgotten is owed that, and a server that only marks
    accounts inactive fills up with the work of people who have left.
    """
    me_ = require_admin(request)
    if me_.id == user_id:
        raise HTTPException(status_code=400, detail="you cannot delete yourself")
    store = _store(request)
    _get_user(store, user_id)
    engine = _engine(request)
    forget_everything(
        store,
        user_id,
        worktrees=engine.workspace.worktrees_root,
        repos=engine.repos_root,
    )
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
    "SIGNED_OUT_HEADER",
    "SIGNED_OUT_INVITED",
    "SIGNED_OUT_REMOVED",
    "TWO_FACTOR_HEADER",
    "Credentials",
    "auth_dependency",
    "current_user",
    "require_admin",
    "require_owner",
    "resolve_user",
    "router",
    "session_from_link",
    "start_session",
]
