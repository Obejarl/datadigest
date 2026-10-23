"""The unit of work: turn one uploaded dataset into a stored profile.

Called by the worker (Redis mode) or by FastAPI BackgroundTasks (inline mode).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import sessionmaker

from datadigest.config import get_settings
from datadigest.core.loader import LoadError, load_csv
from datadigest.core.profile import build_profile
from datadigest.models import Dataset, DatasetFile, Optimization, Status, utcnow
from datadigest.optimize import run as run_optimizer
from datadigest.optimize.common import OptimizationError

log = logging.getLogger(__name__)


def process_dataset(dataset_id: uuid.UUID, factory: sessionmaker) -> Status | None:
    with factory() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:  # deleted while waiting in the queue
            log.info("dataset %s no longer exists, skipping", dataset_id)
            return None
        dataset.status, dataset.started_at = Status.PROCESSING, utcnow()
        db.commit()

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
            dataset.status = Status.DONE

        dataset.finished_at = utcnow()
        db.commit()
        log.info("dataset %s -> %s", dataset_id, dataset.status)
        return Status(dataset.status)


def process_optimization(optimization_id: uuid.UUID, factory: sessionmaker) -> Status | None:
    settings = get_settings()
    with factory() as db:
        opt = db.get(Optimization, optimization_id)
        if opt is None:
            log.info("optimization %s no longer exists, skipping", optimization_id)
            return None
        opt.status, opt.started_at = Status.PROCESSING, utcnow()
        db.commit()

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
            opt.status = Status.DONE

        opt.finished_at = utcnow()
        db.commit()
        log.info("optimization %s (%s) -> %s", optimization_id, opt.kind, opt.status)
        return Status(opt.status)
