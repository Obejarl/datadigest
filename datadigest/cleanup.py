"""Housekeeping, run as a Kubernetes CronJob every 15 minutes:

1. fail jobs that have been queued/processing for too long (a worker crashed
   mid-job, or Redis lost the queue), so users see "failed, try again" instead
   of a spinner that never ends;
2. delete datasets older than RETENTION_DAYS.

python -m datadigest.cleanup
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta

from sqlalchemy import delete, func, update
from sqlalchemy.orm import sessionmaker

from datadigest.config import get_settings
from datadigest.db import SessionLocal
from datadigest.models import Dataset, Optimization, Status, utcnow

log = logging.getLogger("datadigest.cleanup")


def delete_older_than(factory: sessionmaker, days: int, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - timedelta(days=days)
    with factory() as db:
        # One SQL statement instead of loading rows; dataset_files go via ON DELETE CASCADE.
        result = db.execute(delete(Dataset).where(Dataset.created_at < cutoff))
        db.commit()
        return result.rowcount


STUCK_MESSAGE = "Processing did not finish (the worker may have stopped). Try running it again."


def fail_stuck(factory: sessionmaker, minutes: int, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - timedelta(minutes=minutes)
    failed = 0
    with factory() as db:
        for model in (Dataset, Optimization):
            started = func.coalesce(model.queued_at, model.created_at)
            result = db.execute(
                update(model)
                .where(model.status.in_([Status.QUEUED, Status.PROCESSING]), started < cutoff)
                .values(status=Status.FAILED, error=STUCK_MESSAGE, finished_at=now or utcnow())
            )
            failed += result.rowcount
        db.commit()
    return failed


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    stuck = fail_stuck(SessionLocal, settings.stuck_after_minutes)
    log.info("marked %d stuck jobs as failed (older than %d min)", stuck, settings.stuck_after_minutes)
    deleted = delete_older_than(SessionLocal, settings.retention_days)
    log.info("deleted %d datasets older than %d days", deleted, settings.retention_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
