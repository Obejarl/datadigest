"""Budget allocation (multi-dimensional 0/1 knapsack): choose the projects that
give the most value without exceeding any budget.

    max  sum_i v_i x_i
    s.t. sum_i w_ki x_i <= B_k     for every budget k (money, people, hours)
         sum_i x_i <= K            (optional cap on the number of projects)
         x_i in {0, 1}

Solved as a MIP with HiGHS. The LP relaxation gives an upper bound, so the
report can say how close the whole-project answer is to the theoretical best.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from datadigest.optimize.common import (
    EPS,
    GREEN,
    GREY,
    STATUS,
    VIOLET,
    OptimizationError,
    chart,
    check_size,
    envelope,
    fmt,
    infeasible,
    kpi,
    labels,
    numeric,
    table,
    uplift,
    utilisation_chart,
)

KIND = "knapsack"


class Budget(BaseModel):
    column: str
    capacity: float = Field(ge=0)


class KnapsackParams(BaseModel):
    name_column: str = Field(description="Project / item names")
    value_column: str = Field(description="Value of choosing the item (return, score)")
    budgets: list[Budget] = Field(min_length=1, description="Cost columns and the budget for each")
    max_items: int | None = Field(None, ge=1, description="Optional limit on how many items to choose")


def _greedy(v: np.ndarray, W: np.ndarray, B: np.ndarray, max_items: int | None) -> np.ndarray:
    """Rule of thumb: best value per (budget-normalised) cost first, take it if it still fits."""
    weight = (W / np.where(B > EPS, B, 1)[:, None]).sum(axis=0)
    ratio = np.where(weight > EPS, v / np.where(weight > EPS, weight, 1), np.inf)
    x = np.zeros_like(v)
    left = B.copy()
    for i in np.argsort(-ratio):
        if v[i] <= 0 or (max_items and x.sum() >= max_items):
            continue
        if (W[:, i] <= left + EPS).all():
            x[i] = 1
            left -= W[:, i]
    return x


def solve(df: pd.DataFrame, params: KnapsackParams, time_limit: float = 10.0) -> dict:
    check_size(len(df), "items")
    names = labels(df, params.name_column)
    v = numeric(df, params.value_column)
    cols = [b.column for b in params.budgets]
    W = np.vstack([numeric(df, c) for c in cols])
    B = np.array([b.capacity for b in params.budgets], dtype=float)
    if (W < 0).any():
        raise OptimizationError("Costs cannot be negative")
    A, ub = W, B
    if params.max_items:
        A = np.vstack([W, np.ones_like(v)])
        ub = np.append(B, params.max_items)
    label = f"Total {params.value_column}"
    started = time.perf_counter()
    res = milp(
        -v,
        constraints=LinearConstraint(A, -np.inf, ub),
        integrality=np.ones_like(v),
        bounds=Bounds(0, 1),
        options={"time_limit": time_limit},
    )
    status = STATUS.get(res.status, "error")
    solver = {"name": "HiGHS (MIP, binary)", "variables": len(v), "constraints": len(ub)}
    if status == "infeasible":
        return infeasible(
            KIND,
            "max",
            label,
            "No selection fits the budgets.",
            {**solver, "seconds": time.perf_counter() - started},
        )
    if res.x is None:
        raise OptimizationError(f"The solver stopped without a selection ({status})")

    x = np.round(res.x)
    objective = float(v @ x)
    relax = linprog(-v, A_ub=A, b_ub=ub, bounds=(0, 1), method="highs")
    bound = -relax.fun if relax.status == 0 else None
    gap = 100.0 * (bound - objective) / abs(bound) if bound and abs(bound) > EPS else None
    greedy = _greedy(v, W, B, params.max_items)
    base = float(v @ greedy)
    lift = uplift(objective, base, "max")
    elapsed = time.perf_counter() - started

    used = W @ x
    pct = np.where(B > EPS, 100 * used / np.where(B > EPS, B, 1), 0)
    binding = used >= B - 1e-6 * np.maximum(1, B)
    chosen = x > 0.5
    weight = (W / np.where(B > EPS, B, 1)[:, None]).sum(axis=0)
    ratio = np.where(weight > EPS, v / np.where(weight > EPS, weight, 1), np.inf)
    swapped_out = [names[i] for i in range(len(v)) if greedy[i] > 0.5 and not chosen[i]]
    swapped_in = [names[i] for i in range(len(v)) if chosen[i] and greedy[i] < 0.5]

    insights = []
    if lift is not None:
        insights.append(
            f"The optimal selection is worth {fmt(objective)}, {lift:.1f}% more than ranking by "
            f"value-per-cost ({fmt(base)})."
        )
    if swapped_out or swapped_in:
        insights.append(
            f"Compared with the ranking rule, the optimum drops {', '.join(swapped_out) or 'nothing'} "
            f"and adds {', '.join(swapped_in) or 'nothing'}: a better fit for the budgets as a whole."
        )
    for k in range(len(B)):
        insights.append(
            f"{cols[k]}: {fmt(used[k])} of {fmt(B[k])} used ({pct[k]:.0f}%)"
            + (", fully spent." if binding[k] else f", {fmt(B[k] - used[k])} left over.")
        )
    if gap is not None:
        insights.append(
            f"The theoretical (fractional) best is {fmt(bound)}; the whole-project answer is within "
            f"{gap:.2f}% of it."
        )
    rank = {int(i): r + 1 for r, i in enumerate(np.argsort(-ratio))}
    for i in [i for i in np.argsort(-ratio) if not chosen[i] and names[i] not in swapped_out][:1]:
        insights.append(
            f"{names[i]} ranks #{rank[int(i)]} by value per cost but is left out: it does not fit "
            "alongside the chosen set."
        )

    primary = cols[0]
    charts = [
        chart(
            "scatter",
            f"{params.value_column} vs {primary} (green = selected)",
            [
                {
                    "type": "scatter",
                    "mode": "markers+text",
                    "x": W[0].tolist(),
                    "y": v.tolist(),
                    "text": names,
                    "textposition": "top center",
                    "textfont": {"size": 10},
                    "marker": {
                        "size": 14,
                        "color": [GREEN if c else GREY for c in chosen],
                        "line": {"width": 1, "color": "#0b1222"},
                    },
                    "hovertemplate": "%{text}<br>"
                    + primary
                    + ": %{x:,.2f}<br>value: %{y:,.2f}<extra></extra>",
                }
            ],
            {"xaxis": {"title": {"text": primary}}, "yaxis": {"title": {"text": params.value_column}}},
            wide=True,
        ),
        utilisation_chart("budgets", "Budget utilisation", cols, pct.tolist(), binding.tolist()),
        chart(
            "selected",
            f"{params.value_column} of selected items",
            [
                {
                    "type": "bar",
                    "x": [names[i] for i in np.argsort(-v) if chosen[i]],
                    "y": [v[i] for i in np.argsort(-v) if chosen[i]],
                    "marker": {"color": VIOLET},
                }
            ],
        ),
    ]
    rows = [
        [
            names[i],
            v[i],
            *[W[k, i] for k in range(len(B))],
            ratio[i] if np.isfinite(ratio[i]) else None,
            "yes" if chosen[i] else "no",
            "yes" if greedy[i] > 0.5 else "no",
        ]
        for i in np.argsort(-v)
    ]
    return envelope(
        KIND,
        status=status,
        sense="max",
        objective=objective,
        objective_label=label,
        baseline={"name": "Value per cost ranking", "objective": base, "uplift_pct": lift},
        kpis=[
            kpi(
                label,
                fmt(objective),
                sub="MIP optimum" + (" (time limit hit)" if status == "time_limit" else ""),
            ),
            kpi(
                "vs ranking rule",
                f"+{lift:.1f}" if lift is not None else "–",
                "%",
                sub=f"ranking: {fmt(base)}",
                tone="green",
            ),
            kpi("Selected", f"{int(chosen.sum())} / {len(v)}", sub="items chosen", tone="violet"),
            kpi(f"{primary} used", f"{pct[0]:.0f}", "%", sub=f"{fmt(used[0])} of {fmt(B[0])}", tone="amber"),
        ],
        insights=insights,
        tables=[
            table(
                "items",
                "Items",
                ["Item", params.value_column, *cols, "Value/cost index", "Selected", "Ranking pick"],
                rows,
            ),
            table(
                "budgets",
                "Budgets",
                ["Budget", "Available", "Used", "Left", "Utilisation %"],
                [[cols[k], B[k], used[k], B[k] - used[k], pct[k]] for k in range(len(B))],
            ),
        ],
        charts=charts,
        solver={**solver, "seconds": elapsed, "gap_pct": gap},
    )
