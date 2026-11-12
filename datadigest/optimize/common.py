"""Shared building blocks for the optimizers: input checks, limits and solver-result helpers.

The result shape itself (KPIs, insights, tables, charts) is in datadigest/envelope.py, which the
capacity planner uses too; its helpers are re-exported here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from datadigest.envelope import (  # noqa: F401  (re-exported: the solvers import them from here)
    AMBER,
    CYAN,
    GREEN,
    GREY,
    RED,
    VIOLET,
    chart,
    clean,
    envelope,
    fmt,
    kpi,
    table,
)

EPS = 1e-7
MAX_VARIABLES = 20_000
# Hungarian is O(n^3): 1,500 x 1,500 still solves in about a second.
MAX_ASSIGNMENT_SIDE = 1_500
# The what-if curve re-solves the model 16 times; skip it for big models to keep runs short.
MAX_VARIABLES_FOR_WHAT_IF = 2_000


class OptimizationError(ValueError):
    """Bad input for a model. The message is shown to the user as is."""


# ---------------------------------------------------------------- input helpers


def require_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        raise OptimizationError(f"Column '{column}' not found. Available: {', '.join(map(str, df.columns))}")
    return df[column]


def numeric(df: pd.DataFrame, column: str, *, allow_missing: bool = False) -> np.ndarray:
    values = pd.to_numeric(require_column(df, column), errors="coerce")
    if not allow_missing and values.isna().any():
        bad = int(values.isna().sum())
        raise OptimizationError(f"Column '{column}' must be numeric; {bad} value(s) are empty or not numbers")
    return values.to_numpy(dtype=float)


def labels(df: pd.DataFrame, column: str) -> list[str]:
    values = require_column(df, column).astype(str).str.strip()
    if values.duplicated().any():
        dupes = ", ".join(values[values.duplicated()].unique()[:3])
        raise OptimizationError(f"Names in '{column}' must be unique; repeated: {dupes}")
    return values.tolist()


def check_size(count: int, what: str, limit: int = MAX_VARIABLES) -> None:
    """Refuse models that would tie up a worker for minutes; the message says what to do instead."""
    if count > limit:
        raise OptimizationError(
            f"Too many {what} ({count:,}); the limit is {limit:,}. Aggregate or filter the data first."
        )


def numeric_columns(df: pd.DataFrame, exclude: set[str]) -> list[str]:
    return [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]


# ---------------------------------------------------------------- output helpers


def snap(x: np.ndarray) -> np.ndarray:
    """Solver output like 2.9999999 or -1e-12 reads badly; round away float noise."""
    out = np.round(np.asarray(x, dtype=float), 6)
    out[np.abs(out) < 1e-9] = 0.0
    return out


def uplift(optimal: float, baseline: float | None, sense: str) -> float | None:
    """How much better the optimum is than the heuristic, in percent (always >= 0 when both exist)."""
    if baseline is None or abs(baseline) < EPS:
        return None
    gain = (optimal - baseline) if sense == "max" else (baseline - optimal)
    return 100.0 * gain / abs(baseline)


def utilisation_chart(
    chart_id: str, title: str, names: list[str], pct: list[float], binding: list[bool]
) -> dict:
    colours = [AMBER if b else CYAN for b in binding]
    data = [
        {
            "type": "bar",
            "x": names,
            "y": pct,
            "marker": {"color": colours},
            "hovertemplate": "%{x}: %{y:.1f}%<extra></extra>",
        }
    ]
    layout = {
        "yaxis": {"title": {"text": "% used"}, "range": [0, max(105, max(pct or [0]) + 5)]},
        "shapes": [
            {
                "type": "line",
                "xref": "paper",
                "x0": 0,
                "x1": 1,
                "y0": 100,
                "y1": 100,
                "line": {"color": RED, "width": 1.5, "dash": "dot"},
            }
        ],
    }
    return chart(chart_id, title, data, layout)


def infeasible(kind: str, sense: str, objective_label: str, reason: str, solver: dict) -> dict:
    return envelope(
        kind,
        status="infeasible",
        sense=sense,
        objective=None,
        objective_label=objective_label,
        insights=[reason],
        solver=solver,
        kpis=[kpi("Status", "Infeasible", sub="No plan satisfies every constraint", tone="red")],
    )


# HiGHS status codes as returned by scipy's linprog/milp.
STATUS = {0: "optimal", 1: "time_limit", 2: "infeasible", 3: "unbounded", 4: "error"}
