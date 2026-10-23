"""End-to-end tests of the optimization endpoints, in inline and worker mode."""

import pytest

from datadigest.worker import Worker
from tests.conftest import SAMPLES, upload

QUEUE = "datadigest:jobs"


def test_kinds_describe_every_problem(client):
    kinds = client.get("/api/optimize/kinds").json()
    assert {k["key"] for k in kinds} == {"production", "transport", "assignment", "knapsack"}
    assert all(k["schema"]["properties"] and k["example"] for k in kinds)


@pytest.mark.parametrize("kind", ["production", "transport", "assignment", "knapsack"])
def test_example_runs_end_to_end_inline(client, kind):
    r = client.post(f"/api/optimize/examples/{kind}")
    assert r.status_code == 202
    opt = client.get(f"/api/optimizations/{r.json()['id']}").json()
    assert opt["status"] == "done", opt["error"]
    assert opt["result_status"] == "optimal"
    assert opt["result"]["insights"] and opt["objective"] is not None
    assert opt["uplift_pct"] is None or opt["uplift_pct"] >= 0

    report = client.get(f"/api/optimizations/{opt['id']}/report")
    assert report.status_code == 200
    assert "What the optimum tells you" in report.text


def test_optimize_uploaded_dataset_with_custom_params(client):
    dataset_id = upload(client, "factory.csv", (SAMPLES / "opt_production.csv").read_bytes()).json()["id"]
    body = {
        "dataset_id": dataset_id,
        "kind": "production",
        "params": {
            "name_column": "product",
            "objective_column": "profit",
            "resources": [{"column": "machine_hours", "capacity": 300}],
        },
    }
    r = client.post("/api/optimizations", json=body)
    assert r.status_code == 202
    opt = client.get(f"/api/optimizations/{r.json()['id']}").json()
    assert opt["status"] == "done"
    assert opt["name"] == "Production planning · factory.csv"
    assert opt["result"]["solver"]["name"] == "HiGHS (LP)"


def test_bad_column_is_rejected_before_queueing(client):
    dataset_id = upload(client).json()["id"]  # sales.csv has no 'profit' column
    body = {
        "dataset_id": dataset_id,
        "kind": "production",
        "params": {
            "name_column": "category",
            "objective_column": "profit",
            "resources": [{"column": "units", "capacity": 10}],
        },
    }
    r = client.post("/api/optimizations", json=body)
    assert r.status_code == 422
    assert "profit" in r.json()["detail"]


def test_invalid_params_and_unknowns(client):
    dataset_id = upload(client).json()["id"]
    assert (
        client.post(
            "/api/optimizations",
            json={"dataset_id": dataset_id, "kind": "production", "params": {"name_column": "x"}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/optimizations", json={"dataset_id": dataset_id, "kind": "magic", "params": {}}
        ).status_code
        == 422
    )
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        client.post(
            "/api/optimizations",
            json={"dataset_id": missing, "kind": "assignment", "params": {"agent_column": "a"}},
        ).status_code
        == 404
    )
    assert client.post("/api/optimize/examples/magic").status_code == 404
    assert client.get(f"/api/optimizations/{missing}").status_code == 404


def test_solver_input_error_marks_run_failed_with_message(client):
    # The column exists (so the request is accepted) but holds text, which the solver cannot use as a profit.
    dataset_id = upload(client, "factory.csv", (SAMPLES / "opt_production.csv").read_bytes()).json()["id"]
    body = {
        "dataset_id": dataset_id,
        "kind": "production",
        "params": {
            "name_column": "product",
            "objective_column": "product",
            "resources": [{"column": "machine_hours", "capacity": 100}],
        },
    }
    opt_id = client.post("/api/optimizations", json=body).json()["id"]
    opt = client.get(f"/api/optimizations/{opt_id}").json()
    assert opt["status"] == "failed"
    assert "'product' must be numeric" in opt["error"]


def test_duplicate_names_are_reported(client):
    dataset_id = upload(client).json()["id"]  # sales.csv has 5 duplicated rows, so order_id repeats
    body = {
        "dataset_id": dataset_id,
        "kind": "production",
        "params": {
            "name_column": "order_id",
            "objective_column": "revenue",
            "resources": [{"column": "units", "capacity": 100}],
        },
    }
    opt = client.get(f"/api/optimizations/{client.post('/api/optimizations', json=body).json()['id']}").json()
    assert opt["status"] == "failed"
    assert "must be unique" in opt["error"]


def test_worker_mode_queues_and_solves(queued_client, redis, factory):
    r = queued_client.post("/api/optimize/examples/knapsack")
    queue = redis.lrange(QUEUE, 0, -1)
    assert any(item.startswith("optimization:") for item in queue)
    assert any(item.startswith("dataset:") for item in queue)

    worker = Worker(redis, factory, QUEUE)
    while worker.run_once(timeout=1):
        pass
    opt = queued_client.get(f"/api/optimizations/{r.json()['id']}").json()
    assert opt["status"] == "done"
    assert opt["result_status"] == "optimal"


def test_list_and_delete(client):
    first = client.post("/api/optimize/examples/assignment").json()["id"]
    second = client.post("/api/optimize/examples/transport").json()["id"]
    assert [o["id"] for o in client.get("/api/optimizations").json()] == [second, first]
    assert client.delete(f"/api/optimizations/{first}").status_code == 204
    assert client.get(f"/api/optimizations/{first}").status_code == 404


def test_deleting_dataset_removes_its_optimizations(client):
    opt = client.post("/api/optimize/examples/production").json()
    assert client.delete(f"/api/datasets/{opt['dataset_id']}").status_code == 204
    assert client.get(f"/api/optimizations/{opt['id']}").status_code == 404


def test_capacity_uses_measured_history_and_explicit_inputs(client):
    client.post("/api/optimize/examples/assignment")
    measured = client.get("/api/capacity").json()
    assert measured["measured"]["service_samples"] >= 2  # the dataset profile and the solver run
    assert measured["hpa"]["minReplicas"] >= 1

    explicit = client.get("/api/capacity?arrival_per_min=30&service_seconds=6&target_wait_seconds=2").json()
    assert explicit["inputs"]["arrival_per_min"] == 30
    assert explicit["objective"] >= 4  # offered load is 3 busy workers
    assert client.get("/api/capacity?arrival_per_min=-1").status_code == 422
