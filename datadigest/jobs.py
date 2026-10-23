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
from datadigest.models import Dataset, DatasetFile, Status, utcnow

log = logging.getLogger(__name__)


def process_dataset(dataset_id: uuid.UUID, factory: sessionmaker) -> Status | None:
    with factory() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:  # deleted while waiting in the queue
            log.info("dataset %s no longer exists, skipping", dataset_id)
            return None
        dataset.status = Status.PROCESSING
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
