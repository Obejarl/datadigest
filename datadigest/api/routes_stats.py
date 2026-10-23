from fastapi import APIRouter, Depends
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from datadigest import jobqueue
from datadigest.api.deps import get_redis
from datadigest.api.schemas import StatsOut
from datadigest.config import Settings, get_settings
from datadigest.db import get_db
from datadigest.models import Dataset, Status

router = APIRouter(prefix="/api", tags=["stats"])

RECENT_FOR_TIMING = 200


@router.get("/stats", response_model=StatsOut)
def stats(
    db: Session = Depends(get_db),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Totals for the dashboard header: aggregated in SQL, so no rows are loaded."""
    by_status = dict(db.execute(select(Dataset.status, func.count()).group_by(Dataset.status)).all())
    done = Dataset.status == Status.DONE
    rows, warnings, quality = db.execute(
        select(
            func.coalesce(func.sum(Dataset.rows), 0),
            func.coalesce(func.sum(Dataset.warnings_count), 0),
            func.avg(Dataset.quality_score),
        ).where(done)
    ).one()

    # Durations are computed in Python: date arithmetic differs between SQLite and PostgreSQL.
    timings = db.execute(
        select(func.coalesce(Dataset.queued_at, Dataset.created_at), Dataset.finished_at)
        .where(done, Dataset.finished_at.is_not(None))
        .order_by(Dataset.created_at.desc())
        .limit(RECENT_FOR_TIMING)
    ).all()
    seconds = [(finished - created).total_seconds() for created, finished in timings]

    queue_depth = None
    if redis is not None:
        try:
            queue_depth = jobqueue.depth(redis, settings.queue_name)
        except Exception:
            queue_depth = None

    return StatsOut(
        datasets=sum(by_status.values()),
        by_status=by_status,
        rows_profiled=rows,
        warnings_found=warnings,
        avg_quality=round(quality, 1) if quality is not None else None,
        avg_seconds=round(sum(seconds) / len(seconds), 2) if seconds else None,
        mode="worker" if redis is not None else "inline",
        queue_depth=queue_depth,
    )
