from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from datadigest import jobqueue, metrics
from datadigest.api.deps import get_redis
from datadigest.config import Settings, get_settings
from datadigest.db import get_db
from datadigest.models import Dataset, Optimization

router = APIRouter(tags=["health"])


@router.get("/healthz")
def liveness():
    """Is the process alive? Kubernetes restarts the container if this fails.

    Deliberately checks nothing external: a database outage should not make
    Kubernetes restart every API pod.
    """
    return {"status": "ok"}


@router.get("/readyz")
def readiness(db: Session = Depends(get_db), redis: Redis | None = Depends(get_redis)):
    """Can this pod serve traffic? Kubernetes stops routing to it while this fails."""
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    if redis is not None:
        try:
            redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"

    ready = all(v == "ok" for v in checks.values())
    return JSONResponse({"ready": ready, "checks": checks}, status_code=200 if ready else 503)


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics(
    db: Session = Depends(get_db),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    """Prometheus scrape endpoint. Gauges that describe shared state (queue, database)
    are refreshed here, at scrape time, so they are never stale."""
    for model, gauge in ((Dataset, metrics.DATASETS), (Optimization, metrics.OPTIMIZATIONS)):
        counts = dict(db.execute(select(model.status, func.count()).group_by(model.status)).all())
        for status in ("queued", "processing", "done", "failed"):
            gauge.labels(status).set(counts.get(status, 0))
    if redis is not None:
        try:
            for state, n in jobqueue.stats(redis, settings.queue_name).items():
                metrics.QUEUE.labels(state).set(n)
        except Exception:  # metrics must not fail because Redis blinked; /readyz reports that
            pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
