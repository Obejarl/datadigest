"""The Optimize section: run operations-research solvers on an uploaded dataset.

A run belongs to its dataset, so in accounts mode it follows the dataset's owner: members see
and change only the runs on their own datasets, and somebody else's run answers 404.
"""

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker, undefer

from datadigest import jobqueue
from datadigest.api.auth import Identity, current_identity, visible
from datadigest.api.deps import get_redis
from datadigest.api.routes_datasets import create_dataset, schedule
from datadigest.api.schemas import OptimizationOut
from datadigest.config import Settings, get_settings
from datadigest.core.report import render_optimization_report
from datadigest.db import get_db, get_session_factory
from datadigest.jobs import process_optimization
from datadigest.models import Dataset, Optimization, Status
from datadigest.optimize import KINDS, validate
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


def _runs(identity: Identity | None):
    """Runs the caller may see: those on datasets the caller may see."""
    return visible(select(Optimization).join(Dataset, Optimization.dataset_id == Dataset.id), identity)


def _get(
    db: Session, opt_id: uuid.UUID, identity: Identity | None, with_result: bool = False
) -> Optimization:
    query = _runs(identity).where(Optimization.id == opt_id)
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
    identity: Identity | None = Depends(current_identity),
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
        visible(select(Dataset).where(Dataset.id == body.dataset_id), identity).options(
            undefer(Dataset.profile)
        )
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
    identity: Identity | None = Depends(current_identity),
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
    dataset = create_dataset(db, spec.sample, path.read_bytes(), identity)
    schedule(dataset.id, background, factory, redis, settings)
    opt = Optimization(dataset_id=dataset.id, kind=kind, params=spec.example, name=f"{spec.title} · example")
    db.add(opt)
    db.commit()
    _schedule(opt.id, background, factory, redis, settings)
    return opt


@router.get("/optimizations", response_model=list[OptimizationOut])
def list_optimizations(
    limit: int = 50, identity: Identity | None = Depends(current_identity), db: Session = Depends(get_db)
):
    query = _runs(identity).order_by(Optimization.created_at.desc()).limit(min(max(limit, 1), 200))
    return db.scalars(query).all()


@router.get("/optimizations/{opt_id}")
def get_optimization(
    opt_id: uuid.UUID, identity: Identity | None = Depends(current_identity), db: Session = Depends(get_db)
) -> dict:
    opt = _get(db, opt_id, identity, with_result=True)
    return {
        **OptimizationOut.model_validate(opt).model_dump(mode="json"),
        "params": opt.params,
        "result": opt.result,
    }


@router.get("/optimizations/{opt_id}/report", response_class=HTMLResponse)
def get_optimization_report(
    opt_id: uuid.UUID,
    download: bool = False,
    identity: Identity | None = Depends(current_identity),
    db: Session = Depends(get_db),
):
    opt = _get(db, opt_id, identity, with_result=True)
    if opt.status != Status.DONE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Optimization is {opt.status}, not done")
    html = render_optimization_report(opt.result, title=opt.name, kind_title=KINDS[opt.kind].title)
    headers = {}
    if download:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", opt.name).strip("_") or "optimization"
        headers["Content-Disposition"] = f'attachment; filename="{safe}-report.html"'
    return HTMLResponse(html, headers=headers)


@router.delete("/optimizations/{opt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_optimization(
    opt_id: uuid.UUID, identity: Identity | None = Depends(current_identity), db: Session = Depends(get_db)
):
    db.delete(_get(db, opt_id, identity))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
