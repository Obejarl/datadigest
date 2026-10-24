import uuid

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
    assert dataset["created_at"].endswith("Z")  # explicit UTC even though SQLite drops tz
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
    assert redis.lrange("datadigest:jobs", 0, -1) == [f"dataset:{dataset_id}"]
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


def test_quality_score_is_stored(client):
    dataset = client.get(f"/api/datasets/{upload(client).json()['id']}").json()
    profile = client.get(f"/api/datasets/{dataset['id']}/profile").json()
    assert dataset["quality_score"] == profile["summary"]["quality"]["score"]


def test_stats_inline_mode(client):
    empty = client.get("/api/stats").json()
    assert empty["datasets"] == 0 and empty["avg_quality"] is None and empty["mode"] == "inline"

    upload(client, "sales.csv")
    upload(client, "tr_survey.csv")
    upload(client, "bad.csv", b"only_header\n")
    stats = client.get("/api/stats").json()
    assert stats["datasets"] == 3
    assert stats["by_status"] == {"done": 2, "failed": 1}
    assert stats["rows_profiled"] == 1005 + 300
    assert stats["avg_seconds"] is not None and stats["avg_seconds"] >= 0
    assert stats["queue_depth"] is None


def test_stats_worker_mode_reports_queue(queued_client):
    upload(queued_client)
    stats = queued_client.get("/api/stats").json()
    assert stats["mode"] == "worker"
    assert stats["queue_depth"] == 1
    assert stats["by_status"] == {"queued": 1}


def test_reprocess_runs_the_analysis_again(client):
    dataset_id = upload(client).json()["id"]
    first = client.get(f"/api/datasets/{dataset_id}").json()
    r = client.post(f"/api/datasets/{dataset_id}/reprocess")
    assert r.status_code == 202
    again = client.get(f"/api/datasets/{dataset_id}").json()
    assert again["status"] == "done"
    assert again["finished_at"] >= first["finished_at"]


def test_reprocess_after_failure_clears_error(client, factory):
    from datadigest.models import DatasetFile

    dataset_id = upload(client, "bad.csv", b"only_header\n").json()["id"]
    assert client.get(f"/api/datasets/{dataset_id}").json()["status"] == "failed"
    with factory() as db:  # simulate a fixed file, then retry
        db.get(DatasetFile, uuid.UUID(dataset_id)).content = b"a,b\n1,2\n"
        db.commit()
    client.post(f"/api/datasets/{dataset_id}/reprocess")
    dataset = client.get(f"/api/datasets/{dataset_id}").json()
    assert (dataset["status"], dataset["error"]) == ("done", None)


def test_reprocess_refuses_while_queued(queued_client):
    dataset_id = upload(queued_client).json()["id"]
    assert queued_client.post(f"/api/datasets/{dataset_id}/reprocess").status_code == 409


def test_samples_list_and_load(client):
    samples = client.get("/api/samples").json()
    assert {s["name"] for s in samples} == {"sales.csv", "tr_survey.csv"}
    assert all(s["size_bytes"] > 0 and s["description"] for s in samples)

    r = client.post("/api/samples/tr_survey.csv")
    assert r.status_code == 202
    dataset = client.get(f"/api/datasets/{r.json()['id']}").json()
    assert (dataset["filename"], dataset["status"], dataset["rows"]) == ("tr_survey.csv", "done", 300)


def test_samples_reject_unknown_and_traversal(client):
    assert client.post("/api/samples/nope.csv").status_code == 404
    assert client.post("/api/samples/..%2Fpyproject.toml").status_code == 404


def test_security_headers(client):
    headers = client.get("/healthz").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "same-origin"


def test_profile_has_preview_and_quality_breakdown(client):
    dataset_id = upload(client).json()["id"]
    profile = client.get(f"/api/datasets/{dataset_id}/profile").json()
    assert profile["preview"]["columns"][0] == "order_id"
    assert len(profile["preview"]["rows"]) == 20
    assert set(profile["summary"]["quality"]["penalties"]) == {"missing", "duplicates", "warnings"}


def test_pages_are_revalidated_and_reference_versioned_assets(client):
    for path in ["/", "/optimize", "/capacity", "/datasets/x", "/optimizations/x"]:
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache"
        assert "style.css?v=" in r.text


def test_metrics_endpoint_reports_requests_jobs_and_queue(queued_client, redis, factory):
    from datadigest.worker import Worker

    upload(queued_client)
    Worker(redis, factory, "datadigest:jobs", housekeeping_seconds=None).run_once(timeout=1)
    queued_client.get("/api/datasets")
    body = queued_client.get("/metrics").text

    assert 'datadigest_http_requests_total{method="GET",route="/api/datasets",status="200"}' in body
    assert 'datadigest_jobs_total{kind="dataset",status="done"}' in body
    assert 'datadigest_queue_jobs{state="pending"} 0.0' in body
    assert 'datadigest_datasets{status="done"} 1.0' in body
    assert "datadigest_job_duration_seconds_bucket" in body


def test_metrics_use_route_templates_not_raw_ids(client):
    dataset_id = upload(client).json()["id"]
    client.get(f"/api/datasets/{dataset_id}")
    body = client.get("/metrics").text
    assert 'route="/api/datasets/{dataset_id}"' in body
    assert dataset_id not in body
