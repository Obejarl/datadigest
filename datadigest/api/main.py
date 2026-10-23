import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datadigest.api import routes_datasets, routes_health, routes_stats

STATIC = Path(__file__).parent.parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="DataDigest",
    version="0.2.0",
    description="Upload a CSV, get an automatic data-quality profile, charts and an HTML report.",
)
app.include_router(routes_health.router)
app.include_router(routes_datasets.router)
app.include_router(routes_stats.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/datasets/{dataset_id}", include_in_schema=False)
def dataset_page(dataset_id: str):
    return FileResponse(STATIC / "dataset.html")
