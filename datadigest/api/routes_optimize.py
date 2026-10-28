"""Operations-research endpoints: run solvers on datasets, and plan worker capacity."""

import re
import statistics
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker, undefer

from datadigest import jobqueue
from datadigest.api.deps import get_redis
from datadigest.api.routes_datasets import create_dataset, schedule
from datadigest.api.schemas import OptimizationOut
from datadigest.config import Settings, get_settings
from datadigest.core.report import render_optimization_report
from datadigest.db import get_db, get_session_factory
from datadigest.jobs import process_optimization
from datadigest.models import Dataset, Optimization, Status, utcnow
from datadigest.optimize import KINDS, validate
from datadigest.optimize.capacity import CapacityInputs, plan
from datadigest.optimize.common import OptimizationError

router = APIRouter(prefix="/api", tags=["optimize"])


class OptimizationIn(BaseModel):
    dataset_id: uuid.UUID
    kind: str
    params: dict
    name: str | None = Field(None, max_length=255)


def _referenced_columns(params: dict) -> set[str]:
    """Every column name a params object points at (name_column, resources[].column, task_columns...)."""
    found: set[str] = set()
    for key, value in params.items():
        if isinstance(value, str) and (key == "column" or key.endswith("_column")):
            found.add(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found |= _referenced_columns(item)
                elif isinstance(item, str) and key.endswith("_columns"):
                    found.add(item)
    return found


def _schedule(opt_id: uuid.UUID, background: BackgroundTasks, factory, redis, settings: Settings) -> None:
    if redis is not None:
        jobqueue.enqueue(redis, settings.queue_name, opt_id, kind="optimization")
    else:
        background.add_task(process_optimization, opt_id, factory)


def _get(db: Session, opt_id: uuid.UUID, with_result: bool = False) -> Optimization:
    query = select(Optimization).where(Optimization.id == opt_id)
    if with_result:
        query = query.options(undefer(Optimization.result))
    opt = db.scalars(query).first()
    if opt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Optimization not found")
    return opt


@router.get("/optimize/kinds")
def list_kinds():
    """Problem types, their parameter schema and a ready-made example, for building forms."""
    return [
        {
            "key": k.key,
            "title": k.title,
            "summary": k.summary,
            "method": k.method,
            "sample": k.sample,
            "example": k.example,
            "schema": k.params.model_json_schema(),
        }
        for k in KINDS.values()
    ]


@router.post("/optimizations", response_model=OptimizationOut, status_code=status.HTTP_202_ACCEPTED)
def create_optimization(
    body: OptimizationIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    factory: sessionmaker = Depends(get_session_factory),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    try:
        params = validate(body.kind, body.params).model_dump(exclude_none=True)
    except OptimizationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    dataset = db.scalars(
        select(Dataset).where(Dataset.id == body.dataset_id).options(undefer(Dataset.profile))
    ).first()
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    if dataset.source_path:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Optimizers read an uploaded file; server-side files are profiled only"
        )
    # Catch typos in column names now, while the user is still on the form, if the profile is ready.
    if dataset.status == Status.DONE and dataset.profile:
        known = {c["name"] for c in dataset.profile["columns"]}
        missing = sorted(_referenced_columns(params) - known)
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Column(s) not in {dataset.filename}: {', '.join(missing)}",
            )

    opt = Optimization(
        dataset_id=dataset.id,
        kind=body.kind,
        params=params,
        name=(body.name or f"{KINDS[body.kind].title} · {dataset.filename}")[:255],
    )
    db.add(opt)
    db.commit()
    _schedule(opt.id, background, factory, redis, settings)
    return opt


@router.post(
    "/optimize/examples/{kind}", response_model=OptimizationOut, status_code=status.HTTP_202_ACCEPTED
)
def run_example(
    kind: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    factory: sessionmaker = Depends(get_session_factory),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """One click: load the bundled example dataset for this problem type and solve it."""
    if kind not in KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown problem type")
    spec = KINDS[kind]
    path = Path(settings.samples_dir) / spec.sample
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Example data is not installed")
    dataset = create_dataset(db, spec.sample, path.read_bytes())
    schedule(dataset.id, background, factory, redis, settings)
    opt = Optimization(dataset_id=dataset.id, kind=kind, params=spec.example, name=f"{spec.title} · example")
    db.add(opt)
    db.commit()
    _schedule(opt.id, background, factory, redis, settings)
    return opt


@router.get("/optimizations", response_model=list[OptimizationOut])
def list_optimizations(limit: int = 50, db: Session = Depends(get_db)):
    query = select(Optimization).order_by(Optimization.created_at.desc()).limit(min(max(limit, 1), 200))
    return db.scalars(query).all()


@router.get("/optimizations/{opt_id}")
def get_optimization(opt_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    opt = _get(db, opt_id, with_result=True)
    return {
        **OptimizationOut.model_validate(opt).model_dump(mode="json"),
        "params": opt.params,
        "result": opt.result,
    }


@router.get("/optimizations/{opt_id}/report", response_class=HTMLResponse)
def get_optimization_report(opt_id: uuid.UUID, download: bool = False, db: Session = Depends(get_db)):
    opt = _get(db, opt_id, with_result=True)
    if opt.status != Status.DONE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Optimization is {opt.status}, not done")
    html = render_optimization_report(opt.result, title=opt.name, kind_title=KINDS[opt.kind].title)
    headers = {}
    if download:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", opt.name).strip("_") or "optimization"
        headers["Content-Disposition"] = f'attachment; filename="{safe}-report.html"'
    return HTMLResponse(html, headers=headers)


@router.delete("/optimizations/{opt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_optimization(opt_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(_get(db, opt_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ capacity


def measure(db: Session, window_hours: int = 24) -> dict:
    """Arrival rate and service time of DataDigest's own jobs, from the last day of history."""
    since = utcnow() - timedelta(hours=window_hours)
    arrivals = 0
    first = None
    durations, waits = [], []
    for model in (Dataset, Optimization):
        count, earliest = db.execute(
            select(func.count(), func.min(model.created_at)).where(model.created_at >= since)
        ).one()
        arrivals += count
        if earliest is not None:
            earliest = earliest.replace(tzinfo=None)
            first = earliest if first is None else min(first, earliest)
        rows = db.execute(
            select(model.queued_at, model.started_at, model.finished_at)
            .where(model.status == Status.DONE, model.started_at.is_not(None), model.finished_at.is_not(None))
            .order_by(model.created_at.desc())
            .limit(500)
        ).all()
        for queued, started, finished in rows:
            durations.append((finished - started).total_seconds())
            if queued is not None:
                waits.append(max(0.0, (started - queued).total_seconds()))
    minutes = max(60.0, (utcnow().replace(tzinfo=None) - first).total_seconds() / 60) if first else None
    mean = statistics.fmean(durations) if durations else None
    return {
        "window_hours": window_hours,
        "arrivals": arrivals,
        "arrival_per_min": arrivals / minutes if minutes else None,
        "service_samples": len(durations),
        "service_seconds": mean,
        "service_cv": statistics.pstdev(durations) / mean if mean and len(durations) > 1 else None,
        "observed_wait_seconds": statistics.fmean(waits) if waits else None,
    }


@router.get("/capacity")
def capacity(
    arrival_per_min: float | None = Query(None, gt=0, le=10_000),
    service_seconds: float | None = Query(None, gt=0, le=3600),
    target_wait_seconds: float = Query(5.0, gt=0, le=3600),
    worker_cost_per_hour: float = Query(0.05, ge=0),
    wait_cost_per_hour: float = Query(20.0, ge=0),
    peak_factor: float = Query(2.0, ge=1, le=20),
    max_workers: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Size the worker pool with an M/M/c model. Missing inputs are taken from measured history."""
    measured = measure(db)
    defaults = CapacityInputs()
    inputs = CapacityInputs(
        arrival_per_min=arrival_per_min or measured["arrival_per_min"] or defaults.arrival_per_min,
        # Floor at 50 ms: inline-mode jobs on tiny files can measure as ~0,
        # which would make the model trivial.
        service_seconds=service_seconds or max(0.05, measured["service_seconds"] or defaults.service_seconds),
        target_wait_seconds=target_wait_seconds,
        worker_cost_per_hour=worker_cost_per_hour,
        wait_cost_per_hour=wait_cost_per_hour,
        peak_factor=peak_factor,
        max_workers=max_workers,
    )
    return plan(inputs, measured, uses_measured=arrival_per_min is None or service_seconds is None)
