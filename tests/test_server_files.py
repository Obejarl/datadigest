"""Files read from LARGE_DATA_DIR: registration, path safety, engine choice and failures."""

import os
import uuid

import pytest
from sqlalchemy import select

from datadigest import serverfiles
from datadigest.config import Settings, get_settings
from datadigest.core import engines, spark_profile
from datadigest.core.profile import build_profile
from datadigest.models import Dataset, Status
from datadigest.optimize import KINDS
from tests.conftest import SAMPLES

CSV = (SAMPLES / "sales.csv").read_bytes()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    folder = tmp_path / "bigdata"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "large_data_dir", str(folder))
    return folder


def _register(client, name):
    return client.post(f"/api/server-files/{name}")


def test_the_feature_is_off_until_a_directory_is_configured(client):
    body = client.get("/api/server-files").json()
    assert body["enabled"] is False and body["files"] == []
    assert _register(client, "sales.csv").status_code == 404


def test_lists_only_data_files_directly_in_the_directory(client, data_dir):
    (data_dir / "b.csv").write_bytes(CSV)
    (data_dir / "a.tsv").write_bytes(b"x\ty\n1\t2\n")
    (data_dir / "notes.pdf").write_bytes(b"%PDF")
    (data_dir / ".hidden.csv").write_text("x\n1\n", encoding="utf-8")
    (data_dir / "nested").mkdir()
    (data_dir / "nested" / "c.csv").write_text("x\n1\n", encoding="utf-8")
    (data_dir / "part.parquet").mkdir()
    (data_dir / "part.parquet" / "part-0.bin").write_bytes(b"12345")

    body = client.get("/api/server-files").json()
    assert body["enabled"] is True
    assert [(f["name"], f["size_bytes"]) for f in body["files"]] == [
        ("a.tsv", 8),
        ("b.csv", len(CSV)),
        ("part.parquet", 5),
    ]


def test_registering_a_file_profiles_it_from_disk(client, data_dir, factory):
    (data_dir / "orders.csv").write_bytes(CSV)

    response = _register(client, "orders.csv")
    assert response.status_code == 202
    created = response.json()
    assert created["source_path"] == "orders.csv" and created["size_bytes"] == len(CSV)

    done = client.get(f"/api/datasets/{created['id']}").json()
    assert done["status"] == "done" and done["rows"] == 1005
    assert done["engine"] == "pandas"  # small file: auto keeps pandas
    assert client.get(f"/api/datasets/{created['id']}/profile").json()["summary"]["engine"] == "pandas"
    assert client.get(f"/api/datasets/{created['id']}/report").status_code == 200

    with factory() as db:  # nothing was copied into the database
        assert db.get(Dataset, uuid.UUID(created["id"])).file is None


def test_uploaded_datasets_report_the_pandas_engine(client):
    from tests.conftest import upload

    dataset = upload(client).json()
    assert client.get(f"/api/datasets/{dataset['id']}").json()["engine"] == "pandas"


@pytest.mark.parametrize(
    "name",
    [
        "../secret.csv",
        "..\\secret.csv",
        "nested/x.csv",
        "/etc/passwd.csv",
        ".hidden.csv",
        "run.exe",
        "",
        "a\x00.csv",
    ],
)
def test_names_that_escape_or_are_not_data_files_are_refused(data_dir, name):
    (data_dir.parent / "secret.csv").write_text("x\n1\n", encoding="utf-8")
    with pytest.raises(serverfiles.ServerFileError):
        serverfiles.resolve(name, get_settings())


def test_a_symlink_pointing_outside_the_directory_is_refused(data_dir):
    outside = data_dir.parent / "outside.csv"
    outside.write_text("x\n1\n", encoding="utf-8")
    try:
        os.symlink(outside, data_dir / "link.csv")
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks needs extra privileges on this system")
    with pytest.raises(serverfiles.ServerFileError):
        serverfiles.resolve("link.csv", get_settings())


def test_unknown_files_are_404(client, data_dir):
    assert _register(client, "missing.csv").status_code == 404
    assert _register(client, "run.exe").status_code == 404


def test_optimizers_need_an_uploaded_file(client, data_dir):
    (data_dir / "orders.csv").write_bytes(CSV)
    dataset_id = _register(client, "orders.csv").json()["id"]
    response = client.post(
        "/api/optimizations",
        json={"dataset_id": dataset_id, "kind": "production", "params": KINDS["production"].example},
    )
    assert response.status_code == 409
    assert "uploaded file" in response.json()["detail"]


def test_a_file_that_disappears_makes_the_job_fail_cleanly(client, data_dir):
    (data_dir / "orders.csv").write_bytes(CSV)
    dataset_id = _register(client, "orders.csv").json()["id"]
    (data_dir / "orders.csv").unlink()

    response = client.post(f"/api/datasets/{dataset_id}/reprocess")
    assert response.status_code == 202
    failed = client.get(f"/api/datasets/{dataset_id}").json()
    assert failed["status"] == "failed" and failed["error"] == "Unknown file"


def test_big_files_go_to_the_spark_engine(client, data_dir, monkeypatch):
    seen = {}

    def fake_spark(path, settings):
        seen["path"] = path.name
        from datadigest.core.loader import load_csv

        profile = build_profile(load_csv(path.read_bytes()))
        profile["summary"]["engine"] = "spark"
        return profile

    monkeypatch.setattr(engines, "build_profile_spark", fake_spark)
    monkeypatch.setattr(engines, "spark_available", lambda: True)
    monkeypatch.setattr(get_settings(), "spark_min_mb", 0)
    (data_dir / "orders.csv").write_bytes(CSV)

    dataset_id = _register(client, "orders.csv").json()["id"]
    done = client.get(f"/api/datasets/{dataset_id}").json()
    assert seen == {"path": "orders.csv"}
    assert done["status"] == "done" and done["engine"] == "spark"


def test_parquet_without_spark_fails_with_an_install_hint(client, data_dir, monkeypatch):
    monkeypatch.setattr(spark_profile, "spark_available", lambda: False)
    (data_dir / "facts.parquet").write_bytes(b"PAR1")
    dataset_id = _register(client, "facts.parquet").json()["id"]
    failed = client.get(f"/api/datasets/{dataset_id}").json()
    assert failed["status"] == "failed" and "needs pyspark" in failed["error"]


def test_the_queue_carries_server_file_jobs_too(queued_client, redis, factory, data_dir):
    from datadigest.worker import Worker

    (data_dir / "orders.csv").write_bytes(CSV)
    dataset_id = _register(queued_client, "orders.csv").json()["id"]
    assert Worker(redis, factory, "datadigest:jobs").run_once(timeout=1) is True
    with factory() as db:
        dataset = db.scalars(select(Dataset)).one()
        assert str(dataset.id) == dataset_id and dataset.status == Status.DONE and dataset.engine == "pandas"


def test_blank_directory_setting_means_off():
    assert Settings(large_data_dir="  ").large_data_dir is None
