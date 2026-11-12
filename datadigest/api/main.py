import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from datadigest import accounts, metrics, sections
from datadigest.api import (
    auth,
    routes_accounts,
    routes_capacity,
    routes_datasets,
    routes_health,
    routes_optimize,
    routes_samples,
    routes_serverfiles,
    routes_stats,
)
from datadigest.config import get_settings
from datadigest.db import SessionLocal

STATIC = Path(__file__).parent.parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    if settings.accounts_enabled:
        if not settings.secret_key:
            log.warning("SECRET_KEY is not set: sessions end when this process restarts")
        try:
            accounts.bootstrap_admin(SessionLocal, settings)
        except Exception:  # a bad ADMIN_PASSWORD or a missing table must not stop the API
            log.exception("could not create the first administrator")
    yield


app = FastAPI(
    title="DataDigest",
    version="0.8.0",
    description="Upload a CSV, get an automatic data-quality profile, charts and an HTML report. "
    "The Optimize section solves production, transport, assignment and budget models on the same files.",
    lifespan=lifespan,
    openapi_tags=sections.openapi_tags(),
)
app.include_router(routes_health.router)
app.include_router(auth.router)
app.include_router(routes_accounts.router)
app.include_router(routes_datasets.router)
app.include_router(routes_stats.router)
app.include_router(routes_samples.router)
app.include_router(routes_serverfiles.router)
app.include_router(routes_optimize.router)
app.include_router(routes_capacity.router)


# Middleware added later wraps the earlier ones, so the order here is: auth (innermost, so a
# rejected request never reaches a route), then metrics (counts the 401s too), then headers (outermost).
app.middleware("http")(auth.require_auth)


@app.middleware("http")
async def record_metrics(request, call_next):
    """Count and time every request, labelled by route template (/api/datasets/{dataset_id}),
    not by raw path: one label per dataset id would explode Prometheus' memory."""
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    metrics.HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
    metrics.HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    return response


@app.middleware("http")
async def security_headers(request, call_next):
    """Cheap defaults: no MIME sniffing, no framing (clickjacking), no full URLs leaked to other sites."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def page(name: str, path: str) -> HTMLResponse:
    """A static page with the shared parts filled in: the navigation, the section cards and the
    footer links all come from datadigest/sections.py, so no page carries its own copy.

    HTML is revalidated on every visit; it references versioned assets (style.css?v=...),
    so a new release reaches browsers immediately instead of mixing old and new files."""
    html = (STATIC / name).read_text(encoding="utf-8")
    return HTMLResponse(sections.render(html, path), headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return page("index.html", "/")


@app.get("/datasets/{dataset_id}", include_in_schema=False)
def dataset_page(dataset_id: str):
    return page("dataset.html", "/datasets/")


@app.get("/login", include_in_schema=False)
def login_page():
    return page("login.html", "/login")


@app.get("/account", include_in_schema=False)
def account_page():
    return page("account.html", "/account")


@app.get("/optimize", include_in_schema=False)
def optimize_page():
    return page("optimize.html", "/optimize")


@app.get("/optimizations/{optimization_id}", include_in_schema=False)
def optimization_page(optimization_id: str):
    return page("optimization.html", "/optimizations/")


@app.get("/capacity", include_in_schema=False)
def capacity_page():
    return page("capacity.html", "/capacity")
