"""The worker-sizing model (M/M/c) against textbook values, and its endpoint."""

import json

import pytest

from datadigest.capacity import CapacityInputs, erlang_c, metrics, plan
from tests.conftest import upload


def test_erlang_c_known_values():
    assert erlang_c(1, 0.5) == pytest.approx(0.5)  # M/M/1: P(wait) = rho
    assert erlang_c(2, 1.0) == pytest.approx(1 / 3)  # textbook value
    assert erlang_c(3, 3.0) == 1.0  # saturated
    assert erlang_c(5, 0.0) == 0.0


def test_mm1_wait_matches_closed_form():
    lam, mu = 0.5, 1.0  # rho = 0.5, Wq = rho / (mu - lam) = 1
    assert metrics(1, lam, mu, 1)["wait_s"] == pytest.approx(1.0)


def test_capacity_plan_recommends_minimum_meeting_target():
    inputs = CapacityInputs(arrival_per_min=30, service_seconds=6, target_wait_seconds=2)
    result = plan(inputs)
    rec = result["objective"]
    lam, mu = 30 / 60, 1 / 6
    assert metrics(rec, lam, mu, 2)["wait_s"] <= 2
    assert not (
        metrics(rec - 1, lam, mu, 2).get("wait_s", 1e9) <= 2
        and metrics(rec - 1, lam, mu, 2)["utilisation"] <= 0.85
    )
    assert result["hpa"]["maxReplicas"] >= result["hpa"]["minReplicas"] == rec
    json.dumps(result, allow_nan=False)


def test_capacity_uses_measured_history_and_explicit_inputs(client):
    upload(client)
    upload(client, "tr_survey.csv")
    measured = client.get("/api/capacity").json()
    assert measured["measured"]["service_samples"] == 2
    assert measured["hpa"]["minReplicas"] >= 1

    explicit = client.get("/api/capacity?arrival_per_min=30&service_seconds=6&target_wait_seconds=2").json()
    assert explicit["inputs"]["arrival_per_min"] == 30
    assert explicit["objective"] >= 4  # offered load is 3 busy workers
    assert client.get("/api/capacity?arrival_per_min=-1").status_code == 422
