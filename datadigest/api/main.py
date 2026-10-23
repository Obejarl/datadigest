import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datadigest.api import routes_datasets, routes_health, routes_optimize, routes_samples, routes_stats

STATIC = Path(__file__).parent.parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="DataDigest",
    version="0.4.0",
    description="Upload a CSV, get an automatic data-quality profile, charts and an HTML report.",
)
app.include_router(routes_health.router)
app.include_router(routes_datasets.router)
app.include_router(routes_stats.router)
app.include_router(routes_samples.router)
app.include_router(routes_optimize.router)


@app.middleware("http")
async def security_headers(request, call_next):
    """Cheap defaults: no MIME sniffing, no framing (clickjacking), no full URLs leaked to other sites."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/datasets/{dataset_id}", include_in_schema=False)
def dataset_page(dataset_id: str):
    return FileResponse(STATIC / "dataset.html")


@app.get("/optimize", include_in_schema=False)
def optimize_page():
    return FileResponse(STATIC / "optimize.html")


@app.get("/optimizations/{opt_id}", include_in_schema=False)
def optimization_page(opt_id: str):
    return FileResponse(STATIC / "optimization.html")


@app.get("/capacity", include_in_schema=False)
def capacity_page():
    return FileResponse(STATIC / "capacity.html")
