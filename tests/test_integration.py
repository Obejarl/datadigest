"""End-to-end against real PostgreSQL and Redis. Runs in CI; skipped locally unless
TEST_DATABASE_URL and TEST_REDIS_URL are set (schema must exist: alembic upgrade head).

    pytest -m integration
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from datadigest import jobqueue
from datadigest.api.deps import get_redis
from datadigest.api.main import app
from datadigest.db import get_session_factory, make_engine
from datadigest.worker import Worker
from tests.conftest import upload

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REDIS_URL = os.getenv("TEST_REDIS_URL")
QUEUE = "datadigest:test-jobs"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (DATABASE_URL and REDIS_URL), reason="needs TEST_DATABASE_URL and TEST_REDIS_URL"),
]


@pytest.fixture
def stack():
    engine = make_engine(DATABASE_URL)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    redis = jobqueue.connect(REDIS_URL)
    redis.delete(QUEUE)
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_redis] = lambda: redis
    yield TestClient(app), redis, factory
    app.dependency_overrides.clear()
    engine.dispose()


def test_upload_worker_report_delete(stack, monkeypatch):
    client, redis, factory = stack
    from datadigest.config import get_settings

    monkeypatch.setattr(get_settings(), "queue_name", QUEUE)

    dataset_id = upload(client, "tr_survey.csv").json()["id"]
    assert jobqueue.depth(redis, QUEUE) == 1

    assert Worker(redis, factory, QUEUE).run_once(timeout=5)
    dataset = client.get(f"/api/datasets/{dataset_id}").json()
    assert dataset["status"] == "done", dataset["error"]
    assert dataset["rows"] == 300

    profile = client.get(f"/api/datasets/{dataset_id}/profile").json()  # JSONB round-trip
    assert profile["summary"]["encoding"] == "cp1254"
    assert "şehir" in client.get(f"/api/datasets/{dataset_id}/report").text

    assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 404


def test_readyz_with_real_services(stack):
    client, _, _ = stack
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["checks"] == {"database": "ok", "redis": "ok"}
