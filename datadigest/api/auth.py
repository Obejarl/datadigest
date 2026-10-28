"""Optional access control with one shared token (ACCESS_TOKEN).

Off by default, so local use and the demos work as before. When ACCESS_TOKEN is set:

- every page and API call needs it, either as `Authorization: Bearer <token>` (scripts, curl)
  or as a session cookie that the login page sets;
- /healthz and /readyz (Kubernetes probes), /metrics (Prometheus; it exposes counts and route
  names, never data), the login page and static assets stay open;
- unauthenticated pages redirect to /login, unauthenticated API calls get 401.

The cookie holds an HMAC of the token, not the token itself, so the token never sits in the
browser. It is HttpOnly (scripts cannot read it) and SameSite=Lax, so other sites cannot make
the browser send it with a POST or DELETE: that is what protects the state-changing calls.
Wrong tokens are throttled per client address (5 per minute) and compared in constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from datadigest.config import get_settings

COOKIE = "dd_session"
COOKIE_MAX_AGE = 30 * 24 * 3600
OPEN_PATHS = {"/healthz", "/readyz", "/metrics", "/login", "/api/login", "/api/logout", "/api/auth/status"}
OPEN_PREFIXES = ("/static/",)
MAX_FAILURES = 5
WINDOW_SECONDS = 60.0

router = APIRouter(tags=["auth"])
_failures: dict[str, deque[float]] = defaultdict(deque)


def session_value(token: str) -> str:
    return hmac.new(token.encode(), b"datadigest-session", hashlib.sha256).hexdigest()


def is_authenticated(request: Request, token: str) -> bool:
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer " and hmac.compare_digest(header[7:].strip().encode(), token.encode()):
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE, "").encode(), session_value(token).encode())


async def require_auth(request: Request, call_next):
    token = get_settings().access_token
    path = request.url.path
    if not token or path in OPEN_PATHS or path.startswith(OPEN_PREFIXES) or is_authenticated(request, token):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse(
            {"detail": "Authentication required"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
        )
    return RedirectResponse(f"/login?next={quote(path)}", status_code=303)


class LoginIn(BaseModel):
    token: str


@router.get("/api/auth/status")
def auth_status(request: Request):
    token = get_settings().access_token
    return {"required": bool(token), "authenticated": (not token) or is_authenticated(request, token)}


@router.post("/api/login")
def login(body: LoginIn, request: Request, response: Response):
    token = get_settings().access_token
    if not token:
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
    if not hmac.compare_digest(body.token.encode(), token.encode()):
        recent.append(now)
        return JSONResponse({"detail": "That token is not correct."}, status_code=401)
    recent.clear()
    response.set_cookie(
        COOKIE,
        session_value(token),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"required": True, "authenticated": True}


@router.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}
