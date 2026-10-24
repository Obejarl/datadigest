"""Background worker: pull dataset ids from Redis and profile them.

    python -m datadigest.worker

Run as many copies as you like (docker compose --scale, a Kubernetes
Deployment with an HPA): BRPOP hands each job to exactly one of them.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from datadigest import jobqueue
from datadigest.config import get_settings
from datadigest.db import SessionLocal
from datadigest.jobs import process_dataset, process_optimization

log = logging.getLogger("datadigest.worker")

HANDLERS = {"dataset": process_dataset, "optimization": process_optimization}
TRANSIENT_ERRORS = (RedisConnectionError, RedisTimeoutError, OperationalError)
MAX_BACKOFF_SECONDS = 30.0


class Worker:
    def __init__(self, redis: Redis, factory: sessionmaker, queue: str):
        self.redis, self.factory, self.queue = redis, factory, queue
        self.stopping = False

    def stop(self, signum=None, _frame=None) -> None:
        # Kubernetes sends SIGTERM before killing a pod. We finish the current
        # job, then exit, instead of dying halfway through it.
        log.info("received signal %s, finishing current job then exiting", signum)
        self.stopping = True

    def run_once(self, timeout: int = 5) -> bool:
        """Process at most one job. Returns False if the queue stayed empty for `timeout` seconds."""
        job = jobqueue.dequeue(self.redis, self.queue, timeout=timeout)
        if job is None:
            return False
        handler = HANDLERS.get(job.kind)
        if handler is None:
            log.error("unknown job kind %r for %s, dropping it", job.kind, job.id)
            return True
        handler(job.id, self.factory)
        return True

    def run_forever(self, sleep=time.sleep) -> None:
        """Loop until stopped. Outages of Redis or PostgreSQL (for example while a pod starts
        before them) are waited out with exponential backoff instead of crashing the process,
        which would otherwise put the pod into CrashLoopBackOff."""
        log.info("worker started, waiting for jobs on %r", self.queue)
        delay = 1.0
        while not self.stopping:
            try:
                self.run_once()
                delay = 1.0
            except TRANSIENT_ERRORS as exc:
                log.warning(
                    "queue or database unavailable (%s); retrying in %.0f s", type(exc).__name__, delay
                )
                sleep(delay)
                delay = min(delay * 2, MAX_BACKOFF_SECONDS)
        log.info("worker stopped")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if not settings.redis_url:
        log.error("REDIS_URL is not set; the worker needs a queue to read from")
        return 1

    worker = Worker(jobqueue.connect(settings.redis_url), SessionLocal, settings.queue_name)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
