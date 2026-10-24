"""Production planning (product mix): maximise total profit / output under limited resources.

    max  sum_i p_i x_i
    s.t. sum_i a_ri x_i <= b_r      for every resource r   (machine hours, labour, material...)
         l_i <= x_i <= u_i          demand floor and ceiling per product
         x_i integer                (optional)

Solved with HiGHS. The LP duals give each resource's shadow price: how much
profit one more unit of that resource would add. That is the number a manager
actually needs ("is overtime on machine A worth 40/hour?").
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from datadigest.optimize.common import (
    CYAN,
    EPS,
    GREEN,
    MAX_VARIABLES_FOR_WHAT_IF,
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
    snap,
    table,
    uplift,
    utilisation_chart,
)

KIND = "production"
IDLE_PCT_WORTH_MENTIONING = 5.0
PARAMETRIC_STEPS = np.round(np.linspace(0.5, 2.0, 16), 3)


class Resource(BaseModel):
    column: str
    capacity: float = Field(ge=0)


class ProductionParams(BaseModel):
    name_column: str = Field(description="Product names")
    objective_column: str = Field(description="Profit (or output) per unit")
    resources: list[Resource] = Field(min_length=1, description="Usage per unit and available capacity")
    min_column: str | None = Field(None, description="Optional minimum quantity per product")
    max_column: str | None = Field(None, description="Optional maximum quantity (demand) per product")
    integer: bool = Field(False, description="Whole units only (MIP)")


def _solve_lp(p, A, b, lb, ub, time_limit):
    bounds = [(lo, None if np.isinf(hi) else hi) for lo, hi in zip(lb, ub, strict=True)]
    return linprog(-p, A_ub=A, b_ub=b, bounds=bounds, method="highs", options={"time_limit": time_limit})


def _solve(p, A, b, lb, ub, integer, time_limit):
    if not integer:
        res = _solve_lp(p, A, b, lb, ub, time_limit)
        return STATUS.get(res.status, "error"), (snap(res.x) if res.x is not None else None), res
    res = milp(
        -p,
        constraints=LinearConstraint(A, -np.inf, b),
        integrality=np.ones_like(p),
        bounds=Bounds(lb, ub),
        options={"time_limit": time_limit},
    )
    x = snap(np.round(res.x)) if res.x is not None else None
    return STATUS.get(res.status, "error"), x, res


def _greedy(p, A, b, lb, ub, integer):
    """Rule of thumb: make the highest-margin product first, as much as fits, then the next."""
    x = lb.copy()
    left = b - A @ x
    if (left < -EPS).any():
        return None
    for i in np.argsort(-p):
        if p[i] <= 0:
            continue
        use = A[:, i]
        room = np.min(np.where(use > EPS, left / np.where(use > EPS, use, 1), np.inf))
        room = min(room, ub[i] - x[i])
        if np.isinf(room):
            continue
        if integer:
            room = np.floor(room + EPS)
        if room > EPS:
            x[i] += room
            left -= use * room
    return x


def solve(df: pd.DataFrame, params: ProductionParams, time_limit: float = 10.0) -> dict:
    check_size(len(df), "products")
    names = labels(df, params.name_column)
    p = numeric(df, params.objective_column)
    resources = [r.column for r in params.resources]
    A = np.vstack([numeric(df, c) for c in resources])
    b = np.array([r.capacity for r in params.resources], dtype=float)
    lb = (
        np.nan_to_num(numeric(df, params.min_column, allow_missing=True), nan=0.0)
        if params.min_column
        else np.zeros_like(p)
    )
    ub = (
        np.nan_to_num(numeric(df, params.max_column, allow_missing=True), nan=np.inf)
        if params.max_column
        else np.full_like(p, np.inf)
    )
    if (A < 0).any():
        raise OptimizationError("Resource usage cannot be negative")
    if (lb > ub + EPS).any():
        i = int(np.argmax(lb > ub + EPS))
        raise OptimizationError(f"'{names[i]}': minimum {lb[i]:g} is above maximum {ub[i]:g}")

    label = f"Total {params.objective_column}"
    mode = "MIP" if params.integer else "LP"
    started = time.perf_counter()
    status, x, res = _solve(p, A, b, lb, ub, params.integer, time_limit)
    solver = {"name": f"HiGHS ({mode})", "variables": len(p), "constraints": len(b)}

    if status == "infeasible":
        need = A @ lb
        short = [
            f"{r} needs {fmt(need[k])} for the minimum quantities but has {fmt(b[k])}"
            for k, r in enumerate(resources)
            if need[k] > b[k] + EPS
        ]
        reason = "The minimum quantities cannot be produced with the available capacity. " + "; ".join(short)
        return infeasible(KIND, "max", label, reason, {**solver, "seconds": time.perf_counter() - started})
    if status == "unbounded":
        free = [names[i] for i in range(len(p)) if p[i] > 0 and not A[:, i].any() and np.isinf(ub[i])]
        reason = "Profit can grow without limit: " + (
            f"{', '.join(free)} use(s) no resource and have no maximum. Add a max quantity or a resource."
            if free
            else "some products are not limited by any resource or maximum."
        )
        return envelope(
            KIND,
            status="unbounded",
            sense="max",
            objective=None,
            objective_label=label,
            insights=[reason],
            solver={**solver, "seconds": time.perf_counter() - started},
            kpis=[kpi("Status", "Unbounded", tone="red")],
        )
    if x is None:
        raise OptimizationError(f"The solver stopped without a plan ({status}). Try a longer time limit.")

    # Duals come from the LP; for an integer model we solve its relaxation to get them (and the bound).
    relax = res if not params.integer else _solve_lp(p, A, b, lb, ub, time_limit)
    shadow = -snap(relax.ineqlin.marginals) if relax.status == 0 else np.zeros_like(b)
    opportunity = snap(relax.lower.marginals) if relax.status == 0 else np.zeros_like(p)
    objective = float(p @ x)
    gap = None
    if params.integer and relax.status == 0 and abs(relax.fun) > EPS:
        gap = 100.0 * (-relax.fun - objective) / abs(relax.fun)

    used = A @ x
    slack = b - used
    pct = np.where(b > EPS, 100.0 * used / np.where(b > EPS, b, 1), 0.0)
    binding = slack <= 1e-6 * np.maximum(1, b)

    greedy = _greedy(p, A, b, lb, ub, params.integer)
    base_obj = float(p @ greedy) if greedy is not None else None
    lift = uplift(objective, base_obj, "max")

    # What-if: scale the most valuable resource and re-solve.
    bottleneck = int(np.argmax(shadow)) if shadow.max() > EPS else None
    curve = []
    if bottleneck is not None and len(p) <= MAX_VARIABLES_FOR_WHAT_IF:
        for f in PARAMETRIC_STEPS:
            bb = b.copy()
            bb[bottleneck] *= f
            st, xx, _ = _solve(p, A, bb, lb, ub, params.integer, max(1.0, time_limit / 8))
            curve.append(
                (float(f), float(p @ xx) if st in ("optimal", "time_limit") and xx is not None else None)
            )
    elapsed = time.perf_counter() - started

    contribution = p * x
    made = x > EPS
    order = np.argsort(-contribution)
    plan_rows = [
        [
            names[i],
            x[i],
            p[i],
            contribution[i],
            100.0 * contribution[i] / objective if abs(objective) > EPS else 0.0,
            opportunity[i] if not made[i] or abs(x[i] - lb[i]) < EPS else 0.0,
        ]
        for i in order
    ]
    res_rows = [
        [resources[k], b[k], used[k], slack[k], pct[k], shadow[k], "yes" if binding[k] else "no"]
        for k in range(len(b))
    ]

    insights = []
    if base_obj is not None and lift is not None:
        insights.append(
            f"The optimal plan earns {fmt(objective)}, {lift:.1f}% more than the "
            f"'highest margin first' rule of thumb ({fmt(base_obj)})."
        )
    for k in np.argsort(-shadow):
        if binding[k] and shadow[k] > EPS:
            insights.append(
                f"{resources[k]} is a bottleneck (100% used): one more unit of it is worth "
                f"{fmt(shadow[k])} in extra {params.objective_column}."
            )
    for k in range(len(b)):
        if not binding[k] and b[k] > EPS and 100 - pct[k] >= IDLE_PCT_WORTH_MENTIONING:
            insights.append(
                f"{resources[k]} has {fmt(slack[k])} unused ({100 - pct[k]:.0f}% idle): "
                "capacity you could reassign, sell or stop paying for."
            )
    for i in np.where(~made)[0][:5]:
        if opportunity[i] > EPS:
            insights.append(
                f"{names[i]} is not worth making at its current margin: each unit would cost "
                f"{fmt(opportunity[i])} of profit elsewhere, so its margin must rise by that much."
            )
    if gap is not None:
        insights.append(f"Whole units only: the integer plan is within {gap:.2f}% of the fractional optimum.")
    if bottleneck is not None and curve:
        at = dict(curve)
        if at.get(1.5) is not None:
            extra = 0.5 * b[bottleneck]
            gain = at[1.5] - objective
            # The shadow price only holds for small changes; compare it with what +50% really brings.
            if gain < 0.5 * shadow[bottleneck] * extra:
                tight = [
                    resources[k]
                    for k in range(len(b))
                    if k != bottleneck and 100 - pct[k] < IDLE_PCT_WORTH_MENTIONING
                ]
                insights.append(
                    f"Adding {resources[bottleneck]} alone helps less than its shadow price suggests: "
                    "+50% capacity "
                    f"adds only {fmt(gain)} ({100 * gain / objective:.1f}%), because "
                    f"{', '.join(tight) or 'another limit'} run(s) out next. Expand them together."
                )
            else:
                insights.append(
                    f"What-if on {resources[bottleneck]}: +50% capacity raises {params.objective_column} "
                    f"to {fmt(at[1.5])} (+{100 * gain / objective:.1f}%)."
                )

    charts = [
        chart(
            "plan",
            f"{params.objective_column} by product",
            [
                {
                    "type": "bar",
                    "x": [names[i] for i in order],
                    "y": [contribution[i] for i in order],
                    "marker": {"color": VIOLET},
                    "hovertemplate": "%{x}: %{y:,.2f}<extra></extra>",
                }
            ],
        ),
        utilisation_chart("resources", "Resource utilisation", resources, pct.tolist(), binding.tolist()),
        chart(
            "shadow",
            "Shadow price (value of one more unit)",
            [
                {
                    "type": "bar",
                    "x": resources,
                    "y": shadow.tolist(),
                    "marker": {"color": GREEN},
                    "hovertemplate": "%{x}: %{y:,.2f}<extra></extra>",
                }
            ],
        ),
    ]
    if curve:
        charts.append(
            chart(
                "parametric",
                f"What-if: {resources[bottleneck]} capacity vs {params.objective_column}",
                [
                    {
                        "type": "scatter",
                        "mode": "lines+markers",
                        "x": [100 * f for f, _ in curve],
                        "y": [v for _, v in curve],
                        "line": {"color": CYAN, "shape": "spline"},
                        "hovertemplate": "%{x:.0f}%: %{y:,.2f}<extra></extra>",
                    }
                ],
                {
                    "xaxis": {
                        "title": {"text": f"{resources[bottleneck]} capacity (% of today)"},
                        "ticksuffix": "%",
                    },
                    "shapes": [
                        {
                            "type": "line",
                            "x0": 100,
                            "x1": 100,
                            "yref": "paper",
                            "y0": 0,
                            "y1": 1,
                            "line": {"color": "#93A1B4", "dash": "dot"},
                        }
                    ],
                },
                wide=True,
            )
        )

    bottleneck_name = resources[bottleneck] if bottleneck is not None else "none"
    return envelope(
        KIND,
        status=status,
        sense="max",
        objective=objective,
        objective_label=label,
        baseline={"name": "Highest margin first", "objective": base_obj, "uplift_pct": lift},
        kpis=[
            kpi(
                label,
                fmt(objective),
                sub=f"{mode} optimum" + (" (time limit hit)" if status == "time_limit" else ""),
            ),
            kpi(
                "vs rule of thumb",
                f"+{lift:.1f}" if lift is not None else "–",
                "%",
                sub=f"greedy plan: {fmt(base_obj)}" if base_obj is not None else "",
                tone="green",
            ),
            kpi(
                "Bottleneck",
                bottleneck_name,
                sub=f"worth {fmt(shadow[bottleneck])} per extra unit"
                if bottleneck is not None
                else "no resource binds",
                tone="amber",
            ),
            kpi(
                "Products made",
                f"{int(made.sum())} / {len(p)}",
                sub=f"{int(binding.sum())} of {len(b)} resources fully used",
                tone="violet",
            ),
        ],
        insights=insights,
        tables=[
            table(
                "plan",
                "Production plan",
                [
                    "Product",
                    "Quantity",
                    "Unit " + params.objective_column,
                    "Contribution",
                    "Share %",
                    "Opportunity cost",
                ],
                plan_rows,
            ),
            table(
                "resources",
                "Resources",
                ["Resource", "Capacity", "Used", "Slack", "Utilisation %", "Shadow price", "Binding"],
                res_rows,
            ),
        ],
        charts=charts,
        solver={**solver, "seconds": elapsed, "gap_pct": gap},
    )
