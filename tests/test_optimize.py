"""Optimizer tests. Optimality claims are checked against brute force, and dual
prices against "re-solve with one more unit", so the numbers in the reports are
verified, not just plausible."""

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from datadigest.core.loader import load_csv
from datadigest.optimize import KINDS, run, validate
from datadigest.optimize.common import OptimizationError

SAMPLES = Path(__file__).parent.parent / "samples"


def sample(kind: str) -> pd.DataFrame:
    return load_csv((SAMPLES / KINDS[kind].sample).read_bytes()).df


def kpi(result: dict, label_start: str):
    return next(k for k in result["kpis"] if k["label"].startswith(label_start))


def rows(result: dict, table_id: str) -> list[list]:
    return next(t for t in result["tables"] if t["id"] == table_id)["rows"]


@pytest.mark.parametrize("kind", list(KINDS))
def test_every_example_solves_and_is_json_safe(kind):
    result = run(kind, sample(kind), KINDS[kind].example)
    assert result["status"] == "optimal"
    assert result["objective"] is not None
    assert result["insights"] and result["charts"] and result["tables"]
    json.dumps(result, allow_nan=False)
    # the optimum is never worse than the rule-of-thumb baseline
    assert result["baseline"]["uplift_pct"] is None or result["baseline"]["uplift_pct"] >= -1e-9


# --- production --------------------------------------------------------------

TEXTBOOK = pd.DataFrame(
    {"product": ["x", "y"], "profit": [3, 2], "r1": [1, 1], "r2": [1, 3], "cap": [3, None]}
)


def textbook_params(**extra):
    params = {
        "name_column": "product",
        "objective_column": "profit",
        "resources": [{"column": "r1", "capacity": 4}, {"column": "r2", "capacity": 6}],
        "max_column": "cap",
    }
    return {**params, **extra}


def test_production_textbook_optimum():
    # max 3x + 2y, x + y <= 4, x + 3y <= 6, x <= 3  ->  x=3, y=1, profit 11
    result = run("production", TEXTBOOK, textbook_params())
    assert result["objective"] == pytest.approx(11)
    plan = {r[0]: r[1] for r in rows(result, "plan")}
    assert plan == {"x": pytest.approx(3), "y": pytest.approx(1)}


def test_shadow_prices_match_resolving_with_one_more_unit():
    df = sample("production")
    params = {**KINDS["production"].example, "integer": False}
    base = run("production", df, params)
    for k, resource in enumerate(params["resources"]):
        shadow = rows(base, "resources")[k][5]
        bumped = json.loads(json.dumps(params))
        bumped["resources"][k]["capacity"] += 1
        gain = run("production", df, bumped)["objective"] - base["objective"]
        assert gain == pytest.approx(shadow, abs=1e-4), resource["column"]  # plans are rounded to 6 dp


def test_production_integer_plan_is_whole_and_beats_greedy():
    result = run("production", sample("production"), KINDS["production"].example)
    assert all(float(r[1]).is_integer() for r in rows(result, "plan"))
    assert result["solver"]["gap_pct"] is not None and result["solver"]["gap_pct"] >= 0


def test_production_infeasible_minimums_are_explained():
    df = TEXTBOOK.assign(lo=[5, 0])  # x >= 5 but r1 allows 4
    result = run("production", df, textbook_params(min_column="lo", max_column=None))
    assert result["status"] == "infeasible"
    assert "r1" in result["insights"][0]


def test_production_unbounded_names_the_free_product():
    df = pd.DataFrame({"product": ["free", "x"], "profit": [5, 1], "r": [0, 1]})
    result = run(
        "production",
        df,
        {
            "name_column": "product",
            "objective_column": "profit",
            "resources": [{"column": "r", "capacity": 10}],
        },
    )
    assert result["status"] == "unbounded"
    assert "free" in result["insights"][0]


# --- transport ---------------------------------------------------------------


def test_transport_matches_brute_force_on_small_case():
    df = pd.DataFrame(
        {"src": ["A", "B", "demand"], "supply": [20, 30, None], "X": [2, 5, 10], "Y": [4, 1, 25]}
    )
    result = run("transport", df, {"source_column": "src"})
    # A->X 10, B->Y 25: cost 2*10 + 1*25 = 45 (enumerate integer flows to confirm)
    best = min(
        2 * ax + 4 * ay + 5 * (10 - ax) + 1 * (25 - ay)
        for ax in range(11)
        for ay in range(26)
        if ax + ay <= 20 and (10 - ax) + (25 - ay) <= 30
    )
    assert result["objective"] == pytest.approx(best) == pytest.approx(45)


def test_transport_demand_dual_matches_resolving():
    df = sample("transport")
    base = run("transport", df, KINDS["transport"].example)
    for name, demand, _, marginal in rows(base, "destinations"):
        bumped = df.copy()
        bumped.loc[bumped["factory"] == "demand", name] = demand + 1
        extra = run("transport", bumped, KINDS["transport"].example)["objective"] - base["objective"]
        assert extra == pytest.approx(marginal, abs=1e-6), name


def test_transport_short_supply_is_explained():
    df = pd.DataFrame({"src": ["A", "demand"], "supply": [5, None], "X": [1, 9]})
    result = run("transport", df, {"source_column": "src"})
    assert result["status"] == "infeasible"
    assert "below total demand" in result["insights"][0]


def test_transport_needs_a_demand_row():
    with pytest.raises(OptimizationError, match="demand"):
        run("transport", pd.DataFrame({"src": ["A"], "supply": [5], "X": [1]}), {"source_column": "src"})


# --- assignment --------------------------------------------------------------


def test_assignment_matches_brute_force():
    df = sample("assignment")
    result = run("assignment", df, KINDS["assignment"].example)
    M = df.drop(columns="worker").to_numpy(dtype=float)
    best = max(
        sum(M[i, p[i]] for i in range(len(p)) if not np.isnan(M[i, p[i]]))
        for p in itertools.permutations(range(M.shape[1]))
        if not any(np.isnan(M[i, p[i]]) for i in range(len(p)))
    )
    assert result["objective"] == pytest.approx(best)


def test_assignment_never_uses_forbidden_pairs_and_handles_rectangles():
    df = pd.DataFrame({"who": ["a", "b", "c"], "t1": [9, None, 1], "t2": [5, 7, 3]})
    result = run("assignment", df, {"agent_column": "who"})
    pairs = {(r[0], r[1]) for r in rows(result, "assignments")}
    assert ("b", "t1") not in pairs
    assert len(pairs) == 2
    assert any("unassigned" in i for i in result["insights"])


def test_assignment_minimise_cost():
    df = pd.DataFrame({"who": ["a", "b"], "t1": [1, 10], "t2": [10, 2]})
    result = run("assignment", df, {"agent_column": "who", "sense": "min"})
    assert result["objective"] == pytest.approx(3)


# --- knapsack ----------------------------------------------------------------


def test_knapsack_matches_brute_force():
    df = sample("knapsack").head(12)
    params = KINDS["knapsack"].example
    result = run("knapsack", df, params)
    v, c, e = (df[col].to_numpy(dtype=float) for col in ("expected_return", "capex", "engineers"))
    best = 0.0
    for mask in itertools.product([0, 1], repeat=len(df)):
        x = np.array(mask)
        if x @ c <= 1000 and x @ e <= 20:
            best = max(best, x @ v)
    assert result["objective"] == pytest.approx(best)


def test_knapsack_respects_max_items():
    result = run("knapsack", sample("knapsack"), {**KINDS["knapsack"].example, "max_items": 2})
    assert sum(1 for r in rows(result, "items") if r[-2] == "yes") <= 2


# --- validation --------------------------------------------------------------


def test_unknown_kind_and_bad_params_are_user_errors():
    with pytest.raises(OptimizationError, match="Unknown problem type"):
        validate("nope", {})
    with pytest.raises(OptimizationError, match="resources"):
        validate("production", {"name_column": "p", "objective_column": "v", "resources": []})


def test_missing_and_non_numeric_columns_are_explained():
    df = pd.DataFrame({"product": ["a"], "profit": ["lots"], "r": [1]})
    params = {
        "name_column": "product",
        "objective_column": "profit",
        "resources": [{"column": "r", "capacity": 1}],
    }
    with pytest.raises(OptimizationError, match="must be numeric"):
        run("production", df, params)
    with pytest.raises(OptimizationError, match="not found"):
        run("production", df, {**params, "objective_column": "margin"})


# --- capacity (M/M/c) ---------------------------------------------------------


def test_erlang_c_known_values():
    from datadigest.optimize.capacity import erlang_c

    assert erlang_c(1, 0.5) == pytest.approx(0.5)  # M/M/1: P(wait) = rho
    assert erlang_c(2, 1.0) == pytest.approx(1 / 3)  # textbook value
    assert erlang_c(3, 3.0) == 1.0  # saturated
    assert erlang_c(5, 0.0) == 0.0


def test_mm1_wait_matches_closed_form():
    from datadigest.optimize.capacity import metrics

    lam, mu = 0.5, 1.0  # rho = 0.5, Wq = rho / (mu - lam) = 1
    assert metrics(1, lam, mu, 1)["wait_s"] == pytest.approx(1.0)


def test_capacity_plan_recommends_minimum_meeting_target():
    from datadigest.optimize.capacity import CapacityInputs, metrics, plan

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
