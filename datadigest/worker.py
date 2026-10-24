"""Background worker: take jobs from Redis and run them.

    python -m datadigest.worker

Run as many copies as you like (docker compose --scale, a Kubernetes Deployment
with an HPA): BLMOVE hands each job to exactly one of them. A job is acked only
after its handler returns, so a worker that dies mid-job does not lose it: the
housekeeping step gives it back to the queue (see jobqueue.py).
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from prometheus_client import start_http_server
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from datadigest import jobqueue, metrics
from datadigest.config import get_settings
from datadigest.db import SessionLocal
from datadigest.jobs import mark_failed, process_dataset, process_optimization

log = logging.getLogger("datadigest.worker")

HANDLERS = {"dataset": process_dataset, "optimization": process_optimization}
TRANSIENT_ERRORS = (RedisConnectionError, RedisTimeoutError, OperationalError)
MAX_BACKOFF_SECONDS = 30.0


class Worker:
    def __init__(
        self,
        redis: Redis,
        factory: sessionmaker,
        queue: str,
        visibility_seconds: float = 120.0,
        max_attempts: int = 3,
        housekeeping_seconds: float | None = 30.0,
    ):
        self.redis, self.factory, self.queue = redis, factory, queue
        self.visibility_seconds, self.max_attempts = visibility_seconds, max_attempts
        self.housekeeping_seconds = housekeeping_seconds
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
            jobqueue.ack(self.redis, self.queue, job)
            return True
        try:
            handler(job.id, self.factory)
        except TRANSIENT_ERRORS:
            raise  # not acked: it comes back after the visibility timeout; run_forever backs off
        except Exception:
            # A bug or a poison input. Not acked, so it is retried and, if it keeps
            # failing, ends up in the dead-letter list instead of crashing the pod.
            metrics.CRASHES.inc()
            log.exception("job %s crashed (attempt %d); it will be retried", job.raw, job.attempts)
            return True
        jobqueue.ack(self.redis, self.queue, job)
        return True

    def housekeeping(self, now: float | None = None) -> tuple[list, list]:
        requeued, dead = jobqueue.requeue_stale(
            self.redis, self.queue, self.visibility_seconds, self.max_attempts, now=now
        )
        for job in requeued:
            metrics.REQUEUED.inc()
            log.warning(
                "requeued %s: its worker did not finish it within %.0f s", job.raw, self.visibility_seconds
            )
        for job in dead:
            metrics.DEAD.inc()
            log.error("giving up on %s after %d attempts", job.raw, job.attempts)
            mark_failed(
                job.kind,
                job.id,
                self.factory,
                f"Processing failed {job.attempts} times in a row. Try running it again.",
            )
        return requeued, dead

    def run_forever(self, sleep=time.sleep, clock=time.monotonic) -> None:
        """Loop until stopped. Outages of Redis or PostgreSQL (for example while a pod starts
        before them) are waited out with exponential backoff instead of crashing the process,
        which would otherwise put the pod into CrashLoopBackOff."""
        log.info("worker started, waiting for jobs on %r", self.queue)
        delay = 1.0
        next_housekeeping = clock()
        while not self.stopping:
            try:
                if self.housekeeping_seconds is not None and clock() >= next_housekeeping:
                    self.housekeeping()
                    next_housekeeping = clock() + self.housekeeping_seconds
                self.run_once()
                delay = 1.0
            except TRANSIENT_ERRORS as exc:
                metrics.BACKOFFS.inc()
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

    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)  # Prometheus scrapes each worker here
        log.info("metrics on :%d/metrics", settings.worker_metrics_port)
    worker = Worker(
        jobqueue.connect(settings.redis_url),
        SessionLocal,
        settings.queue_name,
        visibility_seconds=settings.job_visibility_seconds,
        max_attempts=settings.max_job_attempts,
    )
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
