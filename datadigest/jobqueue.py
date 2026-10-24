"""A small reliable job queue on Redis lists.

    <queue>             pending jobs: LPUSH adds on the left, workers take from the right (FIFO)
    <queue>:processing  jobs a worker has taken but not finished
    <queue>:taken       hash job -> unix time it was taken
    <queue>:attempts    hash job -> how many times it has been taken
    <queue>:dead        jobs that were taken max_attempts times and never finished

Taking a job is one atomic BLMOVE from the queue to the processing list, so a job is
never in neither place. When the handler returns, the worker acks it (removes it from
processing). If the worker dies first, the job stays in processing; requeue_stale()
moves it back to the queue once it has been out longer than the visibility timeout.

That makes delivery *at least once*: a job can run twice (say the worker finished but
died before the ack). Handlers must be idempotent, and ours are: profiling or solving
again simply overwrites the previous result. RQ, Celery and SQS work the same way.
"""

from __future__ import annotations

import time
import uuid
from typing import NamedTuple

from redis import Redis


def connect(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=True)


class Job(NamedTuple):
    kind: str  # "dataset" (profile a file) or "optimization" (run a solver)
    id: uuid.UUID
    raw: str = ""  # the queue entry, needed to ack it
    attempts: int = 1


def _keys(queue: str) -> tuple[str, str, str, str]:
    return f"{queue}:processing", f"{queue}:taken", f"{queue}:attempts", f"{queue}:dead"


def parse(raw: str, attempts: int = 1) -> Job:
    kind, _, job_id = raw.rpartition(":")
    return Job(kind or "dataset", uuid.UUID(job_id), raw, attempts)  # bare ids were queued by older versions


def enqueue(redis: Redis, queue: str, job_id: uuid.UUID, kind: str = "dataset") -> None:
    redis.lpush(queue, f"{kind}:{job_id}")


def dequeue(redis: Redis, queue: str, timeout: int = 5, now: float | None = None) -> Job | None:
    """Block up to `timeout` seconds for a job and move it to the processing list atomically."""
    processing, taken, attempts, _ = _keys(queue)
    raw = redis.blmove(queue, processing, timeout, "RIGHT", "LEFT")
    if raw is None:
        return None
    pipe = redis.pipeline()
    pipe.hset(taken, raw, now if now is not None else time.time())
    pipe.hincrby(attempts, raw, 1)
    _, tries = pipe.execute()
    return parse(raw, int(tries))


def ack(redis: Redis, queue: str, job: Job) -> None:
    """The job is finished (successfully or with a recorded error): forget it."""
    processing, taken, attempts, _ = _keys(queue)
    pipe = redis.pipeline()
    pipe.lrem(processing, 1, job.raw)
    pipe.hdel(taken, job.raw)
    pipe.hdel(attempts, job.raw)
    pipe.execute()


def requeue_stale(
    redis: Redis, queue: str, visibility_seconds: float, max_attempts: int, now: float | None = None
) -> tuple[list[Job], list[Job]]:
    """Give jobs whose worker vanished back to the queue; park repeat offenders in the dead list.

    Safe to run from every worker at once: LREM tells exactly one caller that it removed the entry.
    """
    processing, taken, attempts, dead = _keys(queue)
    now = now if now is not None else time.time()
    requeued, buried = [], []
    for raw, since in redis.hgetall(taken).items():
        if now - float(since) <= visibility_seconds:
            continue
        if not redis.lrem(processing, 1, raw):  # acked meanwhile, or another worker got here first
            redis.hdel(taken, raw)
            continue
        redis.hdel(taken, raw)
        tries = int(redis.hget(attempts, raw) or 0)
        if tries >= max_attempts:
            redis.hdel(attempts, raw)
            redis.lpush(dead, raw)
            buried.append(parse(raw, tries))
        else:
            redis.rpush(queue, raw)  # right end: it is taken next, it has waited long enough
            requeued.append(parse(raw, tries))
    return requeued, buried


def depth(redis: Redis, queue: str) -> int:
    return redis.llen(queue)


def stats(redis: Redis, queue: str) -> dict[str, int]:
    processing, _, _, dead = _keys(queue)
    pipe = redis.pipeline()
    pipe.llen(queue)
    pipe.llen(processing)
    pipe.llen(dead)
    pending, in_flight, dead_count = pipe.execute()
    return {"pending": pending, "in_flight": in_flight, "dead": dead_count}
