"""The units of work: profile one uploaded dataset, or run one optimization.

Called by the worker (Redis mode) or by FastAPI BackgroundTasks (inline mode).
Both are idempotent, which the at-least-once queue relies on: running a job twice
overwrites the first result with an identical one.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from datadigest import metrics
from datadigest.config import get_settings
from datadigest.core.loader import LoadError, load_csv
from datadigest.core.profile import build_profile
from datadigest.models import Dataset, DatasetFile, Optimization, Status, utcnow
from datadigest.optimize import run as run_optimizer
from datadigest.optimize.common import OptimizationError

log = logging.getLogger(__name__)

MODELS = {"dataset": Dataset, "optimization": Optimization}


def _seconds_between(start: datetime | None, end: datetime) -> float | None:
    # SQLite returns naive datetimes, PostgreSQL aware ones; both are UTC.
    if start is None:
        return None
    return (end.replace(tzinfo=None) - start.replace(tzinfo=None)).total_seconds()


def _start(record, kind: str, db) -> float:
    record.status, record.started_at = Status.PROCESSING, utcnow()
    db.commit()
    wait = _seconds_between(record.queued_at or record.created_at, record.started_at)
    if wait is not None and wait >= 0:
        metrics.JOB_WAIT.labels(kind).observe(wait)
    return time.perf_counter()


def _finish(record, kind: str, db, started: float) -> Status:
    record.finished_at = utcnow()
    db.commit()
    metrics.JOB_DURATION.labels(kind).observe(time.perf_counter() - started)
    metrics.JOBS.labels(kind, record.status).inc()
    return Status(record.status)


def process_dataset(dataset_id: uuid.UUID, factory: sessionmaker) -> Status | None:
    with factory() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:  # deleted while waiting in the queue
            log.info("dataset %s no longer exists, skipping", dataset_id)
            return None
        started = _start(dataset, "dataset", db)

        try:
            raw = db.get(DatasetFile, dataset_id).content
            profile = build_profile(load_csv(raw, max_rows=get_settings().max_rows))
        except LoadError as exc:
            dataset.status, dataset.error = Status.FAILED, str(exc)[:500]
        except Exception:
            log.exception("failed to process dataset %s", dataset_id)
            dataset.status, dataset.error = Status.FAILED, "Unexpected error while processing the file"
        else:
            dataset.profile = profile
            dataset.rows = profile["summary"]["rows"]
            dataset.cols = profile["summary"]["columns"]
            dataset.warnings_count = len(profile["warnings"])
            dataset.quality_score = profile["summary"]["quality"]["score"]
            dataset.status, dataset.error = Status.DONE, None

        status = _finish(dataset, "dataset", db, started)
        log.info("dataset %s -> %s", dataset_id, status)
        return status


def process_optimization(optimization_id: uuid.UUID, factory: sessionmaker) -> Status | None:
    settings = get_settings()
    with factory() as db:
        opt = db.get(Optimization, optimization_id)
        if opt is None:
            log.info("optimization %s no longer exists, skipping", optimization_id)
            return None
        started = _start(opt, "optimization", db)

        try:
            raw = db.get(DatasetFile, opt.dataset_id).content
            df = load_csv(raw, max_rows=settings.max_rows).df
            result = run_optimizer(opt.kind, df, opt.params, time_limit=settings.opt_time_limit_seconds)
        except (LoadError, OptimizationError) as exc:
            opt.status, opt.error = Status.FAILED, str(exc)[:500]
        except Exception:
            log.exception("failed to run optimization %s", optimization_id)
            opt.status, opt.error = Status.FAILED, "Unexpected error while solving the model"
        else:
            # "done" means the solver ran; result_status says whether a plan exists (optimal, infeasible...).
            opt.result = result
            opt.result_status = result["status"]
            opt.objective = result["objective"]
            opt.uplift_pct = (result.get("baseline") or {}).get("uplift_pct")
            opt.status, opt.error = Status.DONE, None

        status = _finish(opt, "optimization", db, started)
        log.info("optimization %s (%s) -> %s", optimization_id, opt.kind, status)
        return status


def mark_failed(kind: str, job_id: uuid.UUID, factory: sessionmaker, message: str) -> None:
    """Record a job the queue gave up on, so the user sees "failed, try again" instead of a spinner."""
    model = MODELS.get(kind)
    if model is None:
        return
    with factory() as db:
        record = db.get(model, job_id)
        if record is not None and record.status != Status.DONE:
            record.status, record.error, record.finished_at = Status.FAILED, message[:500], utcnow()
            db.commit()
