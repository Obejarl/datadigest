"""Operations-research optimizers that run on uploaded datasets.

Each problem type ("kind") has a pydantic params model, a pure solve(df, params)
function and a bundled example. Solvers never touch the database or HTTP, so
they can be tested and reused on their own, like datadigest.core.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
from pydantic import BaseModel, ValidationError

from datadigest.optimize import assignment, knapsack, production, transport
from datadigest.optimize.common import OptimizationError


@dataclass(frozen=True)
class Kind:
    key: str
    title: str
    summary: str
    method: str
    params: type[BaseModel]
    solve: Callable[..., dict]
    sample: str
    example: dict = field(default_factory=dict)


KINDS: dict[str, Kind] = {
    k.key: k
    for k in [
        Kind(
            "production",
            "Production planning",
            "Choose how much of each product to make so total profit is as high as possible within machine, "
            "labour and material limits.",
            "Linear / integer programming (HiGHS) with shadow prices and what-if analysis",
            production.ProductionParams,
            production.solve,
            "opt_production.csv",
            {
                "name_column": "product",
                "objective_column": "profit",
                "resources": [
                    {"column": "machine_hours", "capacity": 600},
                    {"column": "labor_hours", "capacity": 800},
                    {"column": "wood_kg", "capacity": 1800},
                ],
                "min_column": "min_qty",
                "max_column": "max_qty",
                "integer": True,
            },
        ),
        Kind(
            "transport",
            "Transportation",
            "Ship goods from factories to customers at the lowest total cost, meeting every demand "
            "without exceeding any supply.",
            "Linear programming (HiGHS) with dual prices per source and destination",
            transport.TransportParams,
            transport.solve,
            "opt_transport.csv",
            {"source_column": "factory", "supply_column": "supply", "demand_label": "demand"},
        ),
        Kind(
            "assignment",
            "Assignment",
            "Pair workers with tasks one-to-one so the team's total efficiency is as high as possible.",
            "Hungarian algorithm (exact, polynomial time)",
            assignment.AssignmentParams,
            assignment.solve,
            "opt_assignment.csv",
            {"agent_column": "worker", "sense": "max"},
        ),
        Kind(
            "knapsack",
            "Budget allocation",
            "Pick the set of projects with the highest total return that fits the money and people budgets.",
            "0/1 integer programming (HiGHS) with LP bound",
            knapsack.KnapsackParams,
            knapsack.solve,
            "opt_projects.csv",
            {
                "name_column": "project",
                "value_column": "expected_return",
                "budgets": [{"column": "capex", "capacity": 1000}, {"column": "engineers", "capacity": 20}],
            },
        ),
    ]
}


def validate(kind: str, params: dict) -> BaseModel:
    if kind not in KINDS:
        raise OptimizationError(f"Unknown problem type '{kind}'. Choose one of: {', '.join(KINDS)}")
    try:
        return KINDS[kind].params.model_validate(params)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "params"
        raise OptimizationError(f"{where}: {first['msg']}") from exc


def run(kind: str, df: pd.DataFrame, params: dict, time_limit: float = 10.0) -> dict:
    return KINDS[kind].solve(df, validate(kind, params), time_limit=time_limit)
