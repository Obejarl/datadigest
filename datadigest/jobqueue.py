"""A minimal job queue on a Redis list.

The API pushes dataset ids on the left (LPUSH); workers block on the right
(BRPOP), so jobs come out first-in, first-out and each id goes to exactly one
worker. Libraries such as RQ or Celery add retries and result storage on top
of this same idea.
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

from redis import Redis


def connect(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=True)


class Job(NamedTuple):
    kind: str  # "dataset" (profile a file) or "optimization" (run a solver)
    id: uuid.UUID


def enqueue(redis: Redis, queue: str, job_id: uuid.UUID, kind: str = "dataset") -> None:
    redis.lpush(queue, f"{kind}:{job_id}")


def dequeue(redis: Redis, queue: str, timeout: int = 5) -> Job | None:
    item = redis.brpop([queue], timeout=timeout)
    if not item:
        return None
    kind, _, raw = item[1].rpartition(":")
    return Job(kind or "dataset", uuid.UUID(raw))  # bare ids were queued by older versions


def depth(redis: Redis, queue: str) -> int:
    return redis.llen(queue)
