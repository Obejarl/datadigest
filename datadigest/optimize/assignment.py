"""Assignment problem: pair agents with tasks one-to-one for the best team total.

Input is a matrix: one row per agent (worker, machine), one numeric column per
task, cells hold the score (efficiency, profit) or cost (time). An empty cell
means the pairing is not allowed. Solved exactly with the Hungarian algorithm
(scipy's linear_sum_assignment), which is O(n^3) instead of trying n! orders.
"""

from __future__ import annotations

import time
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.optimize import linear_sum_assignment

from datadigest.optimize.common import (
    CYAN,
    EPS,
    GREEN,
    MAX_ASSIGNMENT_SIDE,
    VIOLET,
    OptimizationError,
    chart,
    check_size,
    envelope,
    fmt,
    kpi,
    labels,
    numeric_columns,
    require_column,
    table,
    uplift,
)

KIND = "assignment"
FORBIDDEN = 1e9


class AssignmentParams(BaseModel):
    agent_column: str = Field(description="Agent names (people, machines)")
    task_columns: list[str] | None = Field(None, description="Task columns (default: all numeric)")
    sense: Literal["max", "min"] = Field("max", description="max for scores/profit, min for cost/time")


def _greedy(M: np.ndarray, allowed: np.ndarray, maximize: bool) -> list[tuple[int, int]]:
    """Rule of thumb: take the single best remaining pair, repeat."""
    order = np.argsort(-M if maximize else M, axis=None)
    rows, cols, pairs = set(), set(), []
    for flat in order:
        i, j = np.unravel_index(flat, M.shape)
        if allowed[i, j] and i not in rows and j not in cols:
            pairs.append((int(i), int(j)))
            rows.add(i)
            cols.add(j)
    return pairs


def solve(df: pd.DataFrame, params: AssignmentParams, time_limit: float = 10.0) -> dict:
    check_size(len(df), "agents", MAX_ASSIGNMENT_SIDE)
    agents = labels(df, params.agent_column)
    tasks = [t for t in (params.task_columns or numeric_columns(df, set())) if t != params.agent_column]
    if not tasks:
        raise OptimizationError("No task columns found (numeric columns with scores or costs)")
    check_size(len(tasks), "tasks", MAX_ASSIGNMENT_SIDE)
    for t in tasks:
        require_column(df, t)
    M = df[tasks].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    allowed = ~np.isnan(M)
    maximize = params.sense == "max"
    word = "score" if maximize else "cost"
    started = time.perf_counter()

    work = np.where(allowed, M, -FORBIDDEN if maximize else FORBIDDEN)
    rows, cols = linear_sum_assignment(work, maximize=maximize)
    pairs = [(int(i), int(j)) for i, j in zip(rows, cols, strict=True) if allowed[i, j]]
    objective = float(sum(M[i, j] for i, j in pairs))
    greedy = _greedy(M, allowed, maximize)
    base = float(sum(M[i, j] for i, j in greedy))
    lift = uplift(objective, base, params.sense) if len(greedy) == len(pairs) else None
    elapsed = time.perf_counter() - started

    # How each agent fares against their own favourite task.
    best_j = [
        int(np.nanargmax(M[i]) if maximize else np.nanargmin(M[i])) if allowed[i].any() else None
        for i in range(len(agents))
    ]
    rows_out, sacrifice = [], []
    for i, j in sorted(pairs):
        ranked = sorted((v for v in M[i] if not np.isnan(v)), reverse=maximize)
        rank = ranked.index(M[i, j]) + 1
        bj = best_j[i]
        rows_out.append([agents[i], tasks[j], M[i, j], tasks[bj], M[i, bj], rank])
        sacrifice.append((abs(M[i, bj] - M[i, j]), i, j, bj))
    on_best = sum(1 for r in rows_out if r[5] == 1)
    assigned_agents = {i for i, _ in pairs}
    assigned_tasks = {j for _, j in pairs}

    insights = []
    if lift is not None:
        insights.append(
            f"The optimal assignment has a total {word} of {fmt(objective)}, {lift:.1f}% better than "
            f"picking the best pair first ({fmt(base)})."
        )
    insights.append(
        f"{on_best} of {len(pairs)} agents get their personal best task. The others give up a little "
        f"so the team total is {'as high' if maximize else 'as low'} as possible."
    )
    big = max(sacrifice, default=None)
    if big and big[0] > EPS:
        _, i, j, bj = big
        insights.append(
            f"The biggest individual trade-off: {agents[i]} does {tasks[j]} instead of their best, "
            f"{tasks[bj]} ({fmt(M[i, j])} vs {fmt(M[i, bj])})."
        )
    idle_agents = [agents[i] for i in range(len(agents)) if i not in assigned_agents]
    idle_tasks = [tasks[j] for j in range(len(tasks)) if j not in assigned_tasks]
    if idle_agents:
        insights.append(f"More agents than tasks: {', '.join(idle_agents[:6])} stay unassigned.")
    if idle_tasks:
        insights.append(
            f"More tasks than agents (or no allowed pairing): {', '.join(idle_tasks[:6])} stay open."
        )

    marks = {
        "type": "scatter",
        "mode": "markers",
        "x": [tasks[j] for _, j in pairs],
        "y": [agents[i] for i, _ in pairs],
        "marker": {"symbol": "square-open", "size": 26, "color": "#ffffff", "line": {"width": 2.5}},
        "hoverinfo": "skip",
        "showlegend": False,
    }
    heat = {
        "type": "heatmap",
        "z": np.where(allowed, M, None).tolist(),
        "x": tasks,
        "y": agents,
        "colorscale": [[0, "#1E293B"], [1, CYAN if maximize else VIOLET]],
        "reversescale": not maximize,
        "texttemplate": "%{z}",
        "hovertemplate": "%{y} × %{x}: %{z}<extra></extra>",
    }
    charts = [
        chart(
            "matrix",
            f"{word.title()} matrix (white boxes = optimal assignment)",
            [heat, marks],
            {
                "yaxis": {"autorange": "reversed"},
                "margin": {"l": 110, "r": 20, "t": 10, "b": 60},
                "height": max(320, 42 * len(agents) + 90),
            },
            wide=True,
        ),
        chart(
            "agents",
            f"Assigned vs personal best {word}",
            [
                {
                    "type": "bar",
                    "name": "assigned",
                    "x": [r[0] for r in rows_out],
                    "y": [r[2] for r in rows_out],
                    "marker": {"color": GREEN},
                },
                {
                    "type": "bar",
                    "name": "personal best",
                    "x": [r[0] for r in rows_out],
                    "y": [r[4] for r in rows_out],
                    "marker": {"color": "rgba(148,163,184,0.35)"},
                },
            ],
            {"barmode": "group", "legend": {"orientation": "h", "y": 1.12}},
            wide=True,
        ),
    ]
    return envelope(
        KIND,
        status="optimal",
        sense=params.sense,
        objective=objective,
        objective_label=f"Total {word}",
        baseline={"name": "Best pair first", "objective": base, "uplift_pct": lift},
        kpis=[
            kpi(f"Total {word}", fmt(objective), sub="Hungarian algorithm, exact"),
            kpi(
                "vs greedy",
                f"+{lift:.1f}" if lift is not None else "–",
                "%",
                sub=f"greedy: {fmt(base)}",
                tone="green",
            ),
            kpi("Pairs", f"{len(pairs)}", sub=f"{len(agents)} agents × {len(tasks)} tasks", tone="violet"),
            kpi(
                "On their best task",
                f"{on_best} / {len(pairs)}",
                tone="amber",
                sub=f"average {word} {fmt(objective / len(pairs) if pairs else 0)}",
            ),
        ],
        insights=insights,
        tables=[
            table(
                "assignments",
                "Assignments",
                [
                    "Agent",
                    "Task",
                    word.title(),
                    "Personal best task",
                    f"Best {word}",
                    "Rank of assigned task",
                ],
                rows_out,
            )
        ],
        charts=charts,
        solver={
            "name": "Hungarian (linear_sum_assignment)",
            "variables": int(allowed.sum()),
            "constraints": len(agents) + len(tasks),
            "seconds": elapsed,
        },
    )
