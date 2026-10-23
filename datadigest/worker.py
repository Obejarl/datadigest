"""Background worker: pull dataset ids from Redis and profile them.

    python -m datadigest.worker

Run as many copies as you like (docker compose --scale, a Kubernetes
Deployment with an HPA): BRPOP hands each job to exactly one of them.
"""

from __future__ import annotations

import logging
import signal
import sys

from redis import Redis
from sqlalchemy.orm import sessionmaker

from datadigest import jobqueue
from datadigest.config import get_settings
from datadigest.db import SessionLocal
from datadigest.jobs import process_dataset

log = logging.getLogger("datadigest.worker")


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
        dataset_id = jobqueue.dequeue(self.redis, self.queue, timeout=timeout)
        if dataset_id is None:
            return False
        process_dataset(dataset_id, self.factory)
        return True

    def run_forever(self) -> None:
        log.info("worker started, waiting for jobs on %r", self.queue)
        while not self.stopping:
            self.run_once()
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
