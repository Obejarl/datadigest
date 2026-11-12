"""Optional access control, in one of three modes.

- **off** (the default): local use and the demos work without signing in.
- **token** (ACCESS_TOKEN is set): one shared token for everyone. Scripts send it as
  `Authorization: Bearer <token>`; the login page turns it into a session cookie.
- **accounts** (AUTH_MODE=accounts): people sign in with an email and a password. Members see
  only the datasets they uploaded, administrators see all of them and manage the users. Scripts
  use a personal API token (see datadigest/accounts.py and routes_accounts.py).

In both protected modes:

- /healthz and /readyz (Kubernetes probes), /metrics (Prometheus; it exposes counts and route
  names, never data), the login page and static assets stay open;
- unauthenticated pages redirect to /login, unauthenticated API calls get 401;
- the cookie is HttpOnly (scripts cannot read it) and SameSite=Lax, so other sites cannot make
  the browser send it with a POST or DELETE: that is what protects the state-changing calls.
  In token mode it holds an HMAC of the token, in accounts mode a signed user id with an expiry;
- wrong credentials are throttled per client address (5 per minute) and compared in constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from datadigest import accounts
from datadigest.config import Settings, get_settings
from datadigest.db import get_db, get_session_factory
from datadigest.models import Dataset, Role, User

COOKIE = "dd_session"
COOKIE_MAX_AGE = accounts.SESSION_SECONDS
OPEN_PATHS = {"/healthz", "/readyz", "/metrics", "/login", "/api/login", "/api/logout", "/api/auth/status"}
OPEN_PREFIXES = ("/static/",)
MAX_FAILURES = 5
WINDOW_SECONDS = 60.0

router = APIRouter(tags=["auth"])
_failures: dict[str, deque[float]] = defaultdict(deque)


@dataclass(frozen=True)
class Identity:
    """Who is making the request (accounts mode). Plain data, so it outlives the database session."""

    user_id: uuid.UUID
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN


def mode(settings: Settings) -> str:
    if settings.accounts_enabled:
        return "accounts"
    return "token" if settings.access_token else "off"


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header[:7].lower() == "bearer " else None


# ---------------------------------------------------------------- token mode


def session_value(token: str) -> str:
    return hmac.new(token.encode(), b"datadigest-session", hashlib.sha256).hexdigest()


def is_authenticated(request: Request, token: str) -> bool:
    bearer = _bearer(request)
    if bearer is not None and hmac.compare_digest(bearer.encode(), token.encode()):
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE, "").encode(), session_value(token).encode())


# ---------------------------------------------------------------- accounts mode


def identify(request: Request, settings: Settings) -> Identity | None:
    """Look the caller up from the API token or the session cookie. The user row is read on every
    request, so disabling or deleting an account takes effect at once, not when a cookie expires."""
    factory = request.app.dependency_overrides.get(get_session_factory, get_session_factory)()
    with factory() as db:
        bearer = _bearer(request)
        if bearer is not None:
            user = accounts.user_for_token(db, bearer)
        else:
            user_id = accounts.read_session(request.cookies.get(COOKIE, ""), settings)
            user = db.get(User, user_id) if user_id is not None else None
        if user is None or not user.is_active:
            return None
        return Identity(user.id, user.email, user.role)


def current_identity(request: Request) -> Identity | None:
    """None when accounts are off: then nothing is filtered and datasets have no owner."""
    return getattr(request.state, "identity", None)


def require_admin(
    identity: Identity | None = Depends(current_identity), settings: Settings = Depends(get_settings)
) -> Identity:
    if not settings.accounts_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Accounts are not switched on (AUTH_MODE=accounts)")
    if identity is None or not identity.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an administrator can do this")
    return identity


def visible(query, identity: Identity | None):
    """Narrow a query on Dataset to what the caller may see: members get their own rows."""
    if identity is None or identity.is_admin:
        return query
    return query.where(Dataset.owner_id == identity.user_id)


# ---------------------------------------------------------------- the gate


async def require_auth(request: Request, call_next):
    settings = get_settings()
    path = request.url.path
    how = mode(settings)
    request.state.identity = None
    if how == "off" or path in OPEN_PATHS or path.startswith(OPEN_PREFIXES):
        return await call_next(request)
    if how == "token":
        allowed = is_authenticated(request, settings.access_token)
    else:
        request.state.identity = await run_in_threadpool(identify, request, settings)
        allowed = request.state.identity is not None
    if allowed:
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse(
            {"detail": "Authentication required"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
        )
    return RedirectResponse(f"/login?next={quote(path)}", status_code=303)


class LoginIn(BaseModel):
    token: str | None = None
    email: str | None = None
    password: str | None = None


@router.get("/api/auth/status")
def auth_status(request: Request, settings: Settings = Depends(get_settings)):
    how = mode(settings)
    if how == "accounts":
        identity = identify(request, settings)
        user = {"email": identity.email, "role": identity.role} if identity else None
        return {"required": True, "authenticated": identity is not None, "mode": how, "user": user}
    token = settings.access_token
    authenticated = (not token) or is_authenticated(request, token)
    return {"required": bool(token), "authenticated": authenticated, "mode": how, "user": None}


def _set_cookie(response: Response, request: Request, value: str) -> None:
    response.set_cookie(
        COOKIE,
        value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.post("/api/login")
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    how = mode(settings)
    if how == "off":
        return {"required": False, "authenticated": True}
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = _failures[client]
    while recent and now - recent[0] > WINDOW_SECONDS:
        recent.popleft()
    if len(recent) >= MAX_FAILURES:
        return JSONResponse(
            {"detail": "Too many attempts. Wait a minute and try again."},
            status_code=429,
            headers={"Retry-After": str(int(WINDOW_SECONDS))},
        )
    if how == "accounts":
        user = accounts.authenticate(db, body.email or "", body.password or "")
        if user is None:
            recent.append(now)
            return JSONResponse({"detail": "That email and password do not match."}, status_code=401)
        value = accounts.make_session(user.id, settings)
    else:
        if not hmac.compare_digest((body.token or "").encode(), settings.access_token.encode()):
            recent.append(now)
            return JSONResponse({"detail": "That token is not correct."}, status_code=401)
        value = session_value(settings.access_token)
    recent.clear()
    _set_cookie(response, request, value)
    return {"required": True, "authenticated": True}


@router.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}
