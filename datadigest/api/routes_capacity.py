"""Capacity planning: size the worker pool from DataDigest's own job history."""

import statistics
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from datadigest.capacity import CapacityInputs, plan
from datadigest.db import get_db
from datadigest.models import Dataset, Status, utcnow

router = APIRouter(prefix="/api", tags=["capacity"])


def measure(db: Session, window_hours: int = 24) -> dict:
    """Arrival rate and service time of DataDigest's own jobs, from the last day of history."""
    since = utcnow() - timedelta(hours=window_hours)
    arrivals, first = db.execute(
        select(func.count(), func.min(Dataset.created_at)).where(Dataset.created_at >= since)
    ).one()
    if first is not None:
        first = first.replace(tzinfo=None)
    rows = db.execute(
        select(Dataset.queued_at, Dataset.started_at, Dataset.finished_at)
        .where(
            Dataset.status == Status.DONE, Dataset.started_at.is_not(None), Dataset.finished_at.is_not(None)
        )
        .order_by(Dataset.created_at.desc())
        .limit(500)
    ).all()
    durations, waits = [], []
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
