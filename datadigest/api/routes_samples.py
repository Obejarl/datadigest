"""Bundled demo files, so visitors without a CSV at hand can try the app in one click."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from datadigest.api.deps import get_redis
from datadigest.api.routes_datasets import create_dataset, schedule
from datadigest.api.schemas import DatasetOut
from datadigest.config import Settings, get_settings
from datadigest.db import get_db, get_session_factory

router = APIRouter(prefix="/api/samples", tags=["samples"])

# An allow-list: the name in the URL is never used to build a path on its own.
SAMPLES = {
    "sales.csv": "1,005 synthetic orders with missing values, outliers and duplicate rows",
    "tr_survey.csv": "A Turkish Excel export: ';' separated, Windows-1254, decimal commas",
}
# Inputs for the optimizer examples; loadable by name but not listed on the profiling page.
OPTIMIZER_SAMPLES = {"opt_production.csv", "opt_transport.csv", "opt_assignment.csv", "opt_projects.csv"}


class SampleOut(BaseModel):
    name: str
    description: str
    size_bytes: int


def _path(settings: Settings, name: str) -> Path:
    return Path(settings.samples_dir) / name


@router.get("", response_model=list[SampleOut])
def list_samples(settings: Settings = Depends(get_settings)):
    return [
        SampleOut(name=name, description=text, size_bytes=_path(settings, name).stat().st_size)
        for name, text in SAMPLES.items()
        if _path(settings, name).is_file()
    ]


@router.post("/{name}", response_model=DatasetOut, status_code=status.HTTP_202_ACCEPTED)
def load_sample(
    name: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    factory: sessionmaker = Depends(get_session_factory),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    path = _path(settings, name)
    if (name not in SAMPLES and name not in OPTIMIZER_SAMPLES) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown sample")
    dataset = create_dataset(db, name, path.read_bytes())
    schedule(dataset.id, background, factory, redis, settings)
    return dataset
