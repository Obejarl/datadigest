from functools import lru_cache

from redis import Redis

from datadigest import jobqueue
from datadigest.config import get_settings


@lru_cache
def _redis(url: str) -> Redis:
    return jobqueue.connect(url)


def get_redis() -> Redis | None:
    """None means inline mode: no queue, the API processes uploads itself."""
    url = get_settings().redis_url
    return _redis(url) if url else None
