"""Delete datasets older than RETENTION_DAYS. Runs as a Kubernetes CronJob.

python -m datadigest.cleanup
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from datadigest.config import get_settings
from datadigest.db import SessionLocal
from datadigest.models import Dataset, utcnow

log = logging.getLogger("datadigest.cleanup")


def delete_older_than(factory: sessionmaker, days: int, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - timedelta(days=days)
    with factory() as db:
        # One SQL statement instead of loading rows; dataset_files go via ON DELETE CASCADE.
        result = db.execute(delete(Dataset).where(Dataset.created_at < cutoff))
        db.commit()
        return result.rowcount


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    days = get_settings().retention_days
    deleted = delete_older_than(SessionLocal, days)
    log.info("deleted %d datasets older than %d days", deleted, days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
