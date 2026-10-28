from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from datadigest.api.deps import get_redis
from datadigest.api.main import app
from datadigest.db import Base, get_session_factory, make_engine

SAMPLES = Path(__file__).parent.parent / "samples"


@pytest.fixture
def factory():
    # One shared in-memory connection, so the API and background jobs see the same data.
    engine = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _client(factory, redis):
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_redis] = lambda: redis
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client(factory):
    """Inline mode: no Redis, uploads are processed by BackgroundTasks."""
    yield from _client(factory, None)


@pytest.fixture
def queued_client(factory, redis):
    """Worker mode: uploads are pushed to (fake) Redis."""
    yield from _client(factory, redis)


def upload(client, name: str = "sales.csv", content: bytes | None = None, headers: dict | None = None):
    if content is None:
        content = (SAMPLES / name).read_bytes()
    return client.post("/api/datasets", files={"file": (name, content, "text/csv")}, headers=headers)
