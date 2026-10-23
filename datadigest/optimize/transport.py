"""Transportation problem: ship from sources to destinations at minimum total cost.

Input is the classic transportation tableau: one row per source with its
supply, one column per destination with unit costs, plus a row labelled
"demand". An empty cell means the route is not available.

    min  sum_ij c_ij x_ij
    s.t. sum_j x_ij <= s_i     (cannot ship more than a source has)
         sum_i x_ij >= d_j     (every destination gets its demand)
         x_ij >= 0
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.optimize import linprog

from datadigest.optimize.common import (
    AMBER,
    CYAN,
    EPS,
    GREY,
    MAX_VARIABLES,
    STATUS,
    VIOLET,
    OptimizationError,
    chart,
    envelope,
    fmt,
    infeasible,
    kpi,
    numeric_columns,
    require_column,
    snap,
    table,
    uplift,
    utilisation_chart,
)

KIND = "transport"


class TransportParams(BaseModel):
    source_column: str = Field(description="Source names (factories, warehouses)")
    supply_column: str = Field("supply", description="Units available at each source")
    demand_label: str = Field("demand", description="Label of the row that holds the demands")
    destination_columns: list[str] | None = Field(
        None, description="Destination columns (default: all other numeric)"
    )


def _parse(df: pd.DataFrame, params: TransportParams):
    src = require_column(df, params.source_column).astype(str).str.strip()
    require_column(df, params.supply_column)
    is_demand = src.str.lower() == params.demand_label.lower()
    if is_demand.sum() != 1:
        raise OptimizationError(
            f"Add exactly one row named '{params.demand_label}' holding each destination's demand"
        )
    dests = params.destination_columns or numeric_columns(df, {params.source_column, params.supply_column})
    if not dests:
        raise OptimizationError("No destination columns found (numeric columns with unit costs)")
    for d in dests:
        require_column(df, d)

    body = df[~is_demand.to_numpy()]
    sources = src[~is_demand].tolist()
    if len(set(sources)) != len(sources):
        raise OptimizationError("Source names must be unique")
    supply = pd.to_numeric(body[params.supply_column], errors="coerce").to_numpy(dtype=float)
    demand = pd.to_numeric(df[is_demand.to_numpy()][dests].iloc[0], errors="coerce").to_numpy(dtype=float)
    cost = body[dests].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if np.isnan(supply).any() or (supply < 0).any():
        raise OptimizationError(f"'{params.supply_column}' must be a non-negative number for every source")
    if np.isnan(demand).any() or (demand < 0).any():
        raise OptimizationError("Every destination needs a non-negative demand in the demand row")
    return sources, [str(d) for d in dests], supply, demand, cost


def _least_cost(cost: np.ndarray, supply: np.ndarray, demand: np.ndarray) -> np.ndarray | None:
    """Textbook heuristic: fill the cheapest available route first, then the next cheapest."""
    s, d = supply.copy(), demand.copy()
    x = np.zeros_like(cost)
    for flat in np.argsort(np.where(np.isnan(cost), np.inf, cost), axis=None):
        i, j = np.unravel_index(flat, cost.shape)
        if np.isnan(cost[i, j]):
            break
        q = min(s[i], d[j])
        if q > EPS:
            x[i, j] += q
            s[i] -= q
            d[j] -= q
    return x if (d <= EPS).all() else None


def solve(df: pd.DataFrame, params: TransportParams, time_limit: float = 10.0) -> dict:
    sources, dests, supply, demand, cost = _parse(df, params)
    m, n = cost.shape
    routes = [(i, j) for i in range(m) for j in range(n) if not np.isnan(cost[i, j])]
    if len(routes) > MAX_VARIABLES:
        raise OptimizationError(f"Too many routes ({len(routes)}); the limit is {MAX_VARIABLES}")
    label = "Total transport cost"
    solver = {"name": "HiGHS (LP)", "variables": len(routes), "constraints": m + n}
    started = time.perf_counter()

    total_s, total_d = supply.sum(), demand.sum()
    if total_s + EPS < total_d:
        return infeasible(
            KIND,
            "min",
            label,
            f"Total supply {fmt(total_s, 0)} is below total demand {fmt(total_d, 0)}: "
            f"{fmt(total_d - total_s, 0)} units cannot be delivered. Add supply or lower demand.",
            {**solver, "seconds": time.perf_counter() - started},
        )

    c = np.array([cost[i, j] for i, j in routes])
    A = np.zeros((m + n, len(routes)))
    for k, (i, j) in enumerate(routes):
        A[i, k] = 1.0  # supply row:  sum_j x_ij <= s_i
        A[m + j, k] = -1.0  # demand row: -sum_i x_ij <= -d_j
    b = np.concatenate([supply, -demand])
    res = linprog(c, A_ub=A, b_ub=b, bounds=(0, None), method="highs", options={"time_limit": time_limit})
    status = STATUS.get(res.status, "error")
    if status == "infeasible":
        unreachable = [dests[j] for j in range(n) if demand[j] > EPS and np.isnan(cost[:, j]).all()]
        reason = "No feasible plan: " + (
            f"{', '.join(unreachable)} cannot be reached by any route."
            if unreachable
            else "the available routes cannot carry the demand."
        )
        return infeasible(KIND, "min", label, reason, {**solver, "seconds": time.perf_counter() - started})
    if res.x is None:
        raise OptimizationError(f"The solver stopped without a plan ({status})")

    x = np.zeros((m, n))
    for k, (i, j) in enumerate(routes):
        x[i, j] = res.x[k]
    x = snap(x)
    objective = float(np.nansum(np.where(np.isnan(cost), 0, cost) * x))
    # HiGHS marginals are d(cost)/d(rhs) and are <= 0 for "<=" rows. Supply rows: one more unit of s_i
    # lowers cost by -m_i. Demand rows are written as -sum x <= -d_j,
    # so one more unit of d_j raises cost by -m_j.
    duals = -snap(res.ineqlin.marginals)
    supply_value, demand_cost = duals[:m], duals[m:]

    greedy = _least_cost(cost, supply, demand)
    base = float(np.nansum(np.where(np.isnan(cost), 0, cost) * greedy)) if greedy is not None else None
    saving = uplift(objective, base, "min")
    elapsed = time.perf_counter() - started

    shipped = x.sum(axis=1)
    util = np.where(supply > EPS, 100 * shipped / np.where(supply > EPS, supply, 1), 0)
    full = shipped >= supply - 1e-6 * np.maximum(1, supply)
    flows = [(sources[i], dests[j], x[i, j], cost[i, j]) for i in range(m) for j in range(n) if x[i, j] > EPS]
    flows.sort(key=lambda f: -f[2])
    units = float(x.sum())

    insights = []
    if saving is not None:
        insights.append(
            f"The optimal plan costs {fmt(objective)}, {saving:.1f}% less than the least-cost-cell "
            f"heuristic ({fmt(base)}): a saving of {fmt(base - objective)}."
        )
    for i in np.argsort(-supply_value):
        if full[i] and supply_value[i] > EPS:
            insights.append(
                f"{sources[i]} ships everything it has; each extra unit of supply there would save "
                f"{fmt(supply_value[i])} in total cost."
            )
    for i in range(m):
        if not full[i] and supply[i] > EPS:
            insights.append(
                f"{sources[i]} keeps {fmt(supply[i] - shipped[i], 0)} units ({100 - util[i]:.0f}%) unused."
            )
    if n:
        j = int(np.argmax(demand_cost))
        insights.append(
            f"{dests[j]} is the most expensive destination to serve: one more unit of demand there "
            f"adds {fmt(demand_cost[j])} to the total cost."
        )
    insights.append(
        f"{len(flows)} of {len(routes)} available routes are used, moving {fmt(units, 0)} units "
        f"at {fmt(objective / units if units else 0)} per unit on average."
    )

    node_labels = sources + dests
    sankey = {
        "type": "sankey",
        "node": {
            "label": node_labels,
            "pad": 18,
            "thickness": 16,
            "color": [CYAN] * m + [VIOLET] * n,
            "line": {"width": 0},
        },
        "link": {
            "source": [sources.index(f[0]) for f in flows],
            "target": [m + dests.index(f[1]) for f in flows],
            "value": [f[2] for f in flows],
            "color": "rgba(34,211,238,0.28)",
            "hovertemplate": "%{source.label} → %{target.label}: %{value:,.0f}<extra></extra>",
        },
    }
    cost_text = [
        [("" if np.isnan(cost[i, j]) else f"{x[i, j]:,.0f}" if x[i, j] > EPS else "") for j in range(n)]
        for i in range(m)
    ]
    charts = [
        chart(
            "flows",
            "Shipments (width = units)",
            [sankey],
            {"height": max(320, 40 * max(m, n) + 80)},
            wide=True,
        ),
        utilisation_chart("supply", "Supply used per source", sources, util.tolist(), full.tolist()),
        chart(
            "marginal",
            "Marginal cost of one more unit of demand",
            [
                {
                    "type": "bar",
                    "x": dests,
                    "y": demand_cost.tolist(),
                    "marker": {"color": AMBER},
                    "hovertemplate": "%{x}: %{y:,.2f}<extra></extra>",
                }
            ],
        ),
        chart(
            "matrix",
            "Unit costs (numbers = units shipped)",
            [
                {
                    "type": "heatmap",
                    "z": np.where(np.isnan(cost), None, cost).tolist(),
                    "x": dests,
                    "y": sources,
                    "text": cost_text,
                    "texttemplate": "%{text}",
                    "colorscale": [[0, "#0f2a2f"], [1, GREY]],
                    "showscale": False,
                    "hovertemplate": "%{y} → %{x}: cost %{z}<extra></extra>",
                }
            ],
            {"yaxis": {"autorange": "reversed"}, "margin": {"l": 100, "r": 20, "t": 10, "b": 60}},
        ),
    ]
    return envelope(
        KIND,
        status=status,
        sense="min",
        objective=objective,
        objective_label=label,
        baseline={"name": "Least-cost cell first", "objective": base, "uplift_pct": saving},
        kpis=[
            kpi(label, fmt(objective), sub="LP optimum"),
            kpi(
                "Saving vs heuristic",
                f"{saving:.1f}" if saving is not None else "–",
                "%",
                sub=f"heuristic: {fmt(base)}" if base is not None else "",
                tone="green",
            ),
            kpi(
                "Units shipped",
                fmt(units, 0),
                sub=f"supply {fmt(total_s, 0)} · demand {fmt(total_d, 0)}",
                tone="violet",
            ),
            kpi(
                "Routes used",
                f"{len(flows)} / {len(routes)}",
                sub=f"{fmt(objective / units if units else 0)} per unit",
                tone="amber",
            ),
        ],
        insights=insights,
        tables=[
            table(
                "shipments",
                "Shipments",
                ["From", "To", "Units", "Unit cost", "Cost"],
                [[a, b_, q, c_, q * c_] for a, b_, q, c_ in flows],
            ),
            table(
                "sources",
                "Sources",
                ["Source", "Supply", "Shipped", "Unused", "Utilisation %", "Saving per +1 supply"],
                [
                    [sources[i], supply[i], shipped[i], supply[i] - shipped[i], util[i], supply_value[i]]
                    for i in range(m)
                ],
            ),
            table(
                "destinations",
                "Destinations",
                ["Destination", "Demand", "Received", "Cost of +1 demand"],
                [[dests[j], demand[j], x[:, j].sum(), demand_cost[j]] for j in range(n)],
            ),
        ],
        charts=charts,
        solver={**solver, "seconds": elapsed},
    )
