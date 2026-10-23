from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from datadigest.api.deps import get_redis
from datadigest.db import get_db

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
