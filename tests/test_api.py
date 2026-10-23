from sqlalchemy import func, select

from datadigest.config import Settings, get_settings
from datadigest.models import DatasetFile
from tests.conftest import upload


def test_upload_is_processed_inline(client):
    r = upload(client)
    assert r.status_code == 202
    assert r.json()["status"] == "queued"

    # TestClient runs BackgroundTasks before returning, so the job is already done.
    dataset = client.get(f"/api/datasets/{r.json()['id']}").json()
    assert dataset["status"] == "done"
    assert (dataset["rows"], dataset["cols"]) == (1005, 11)
    assert dataset["warnings_count"] > 0


def test_profile_charts_and_report(client):
    dataset_id = upload(client).json()["id"]

    profile = client.get(f"/api/datasets/{dataset_id}/profile").json()
    assert profile["summary"]["rows"] == 1005

    charts = client.get(f"/api/datasets/{dataset_id}/charts").json()
    assert any(c["id"] == "correlation" for c in charts)

    report = client.get(f"/api/datasets/{dataset_id}/report")
    assert report.headers["content-type"].startswith("text/html")
    assert "unit_price" in report.text
    assert "content-disposition" not in report.headers

    download = client.get(f"/api/datasets/{dataset_id}/report?download=true")
    assert download.headers["content-disposition"] == 'attachment; filename="sales-report.html"'


def test_list_newest_first_without_profiles(client):
    upload(client, "sales.csv")
    upload(client, "tr_survey.csv")
    items = client.get("/api/datasets").json()
    assert [d["filename"] for d in items] == ["tr_survey.csv", "sales.csv"]
    assert "profile" not in items[0]


def test_unparseable_file_fails_with_message(client):
    dataset_id = upload(client, "bad.csv", b"only_header\n").json()["id"]
    dataset = client.get(f"/api/datasets/{dataset_id}").json()
    assert dataset["status"] == "failed"
    assert dataset["error"] == "File has no data rows"
    assert client.get(f"/api/datasets/{dataset_id}/profile").status_code == 409


def test_rejects_wrong_extension(client):
    assert upload(client, "data.xlsx", b"a,b\n1,2\n").status_code == 415


def test_rejects_empty_file(client):
    assert upload(client, "empty.csv", b"  \n").status_code == 400


def test_rejects_too_large_file(client):
    from datadigest.api.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(max_upload_mb=1)
    big = b"a,b\n" + b"1,2\n" * 300_000  # ~1.2 MB
    assert upload(client, "big.csv", big).status_code == 413


def test_delete_removes_dataset_and_file(client, factory):
    dataset_id = upload(client).json()["id"]
    assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 404
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(DatasetFile)) == 0


def test_not_found_and_invalid_id(client):
    missing = "00000000-0000-0000-0000-000000000000"
    for path in ["", "/profile", "/charts", "/report"]:
        assert client.get(f"/api/datasets/{missing}{path}").status_code == 404
    assert client.delete(f"/api/datasets/{missing}").status_code == 404
    assert client.get("/api/datasets/not-a-uuid").status_code == 422


def test_upload_in_worker_mode_is_queued(queued_client, redis):
    dataset_id = upload(queued_client).json()["id"]
    assert redis.lrange("datadigest:jobs", 0, -1) == [dataset_id]
    assert queued_client.get(f"/api/datasets/{dataset_id}").json()["status"] == "queued"


def test_health(client, queued_client):
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = queued_client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}


def test_readyz_reports_broken_redis(factory):
    import redis as redis_lib
    from fastapi.testclient import TestClient

    from datadigest.api.deps import get_redis
    from datadigest.api.main import app
    from datadigest.db import get_session_factory

    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_redis] = lambda: redis_lib.Redis(port=1, socket_connect_timeout=0.2)
    try:
        r = TestClient(app).get("/readyz")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503
    assert r.json()["checks"]["redis"].startswith("error")
