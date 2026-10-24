import logging
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datadigest import metrics
from datadigest.api import routes_datasets, routes_health, routes_optimize, routes_samples, routes_stats

STATIC = Path(__file__).parent.parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="DataDigest",
    version="0.5.0",
    description="Upload a CSV, get an automatic data-quality profile, charts and an HTML report.",
)
app.include_router(routes_health.router)
app.include_router(routes_datasets.router)
app.include_router(routes_stats.router)
app.include_router(routes_samples.router)
app.include_router(routes_optimize.router)


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


def page(name: str) -> FileResponse:
    # HTML is revalidated on every visit; it references versioned assets (style.css?v=...),
    # so a new release reaches browsers immediately instead of mixing old and new files.
    return FileResponse(STATIC / name, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return page("index.html")


@app.get("/datasets/{dataset_id}", include_in_schema=False)
def dataset_page(dataset_id: str):
    return page("dataset.html")


@app.get("/optimize", include_in_schema=False)
def optimize_page():
    return page("optimize.html")


@app.get("/optimizations/{opt_id}", include_in_schema=False)
def optimization_page(opt_id: str):
    return page("optimization.html")


@app.get("/capacity", include_in_schema=False)
def capacity_page():
    return page("capacity.html")
