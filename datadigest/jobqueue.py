"""A minimal job queue on a Redis list.

The API pushes dataset ids on the left (LPUSH); workers block on the right
(BRPOP), so jobs come out first-in, first-out and each id goes to exactly one
worker. Libraries such as RQ or Celery add retries and result storage on top
of this same idea.
"""

from __future__ import annotations

import uuid

from redis import Redis


def connect(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=True)


def enqueue(redis: Redis, queue: str, dataset_id: uuid.UUID) -> None:
    redis.lpush(queue, str(dataset_id))


def dequeue(redis: Redis, queue: str, timeout: int = 5) -> uuid.UUID | None:
    item = redis.brpop([queue], timeout=timeout)
    return uuid.UUID(item[1]) if item else None


def depth(redis: Redis, queue: str) -> int:
    return redis.llen(queue)
