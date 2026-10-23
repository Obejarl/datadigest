"""Shared building blocks for the optimizers.

Every solver returns the same envelope, so one renderer (dashboard and HTML
report) can show any problem type:

    {kind, status, sense, objective, objective_label, baseline, kpis,
     insights, tables, charts, solver}
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

CYAN, VIOLET, GREEN, AMBER, RED, GREY = "#22D3EE", "#A78BFA", "#10E39A", "#FFC857", "#FF4D6D", "#64748B"
EPS = 1e-7
MAX_VARIABLES = 20_000


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


def numeric_columns(df: pd.DataFrame, exclude: set[str]) -> list[str]:
    return [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]


# ---------------------------------------------------------------- output helpers


def clean(value: Any) -> Any:
    """Make numpy scalars and NaN/inf JSON-safe, recursively."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return None if math.isnan(value) or math.isinf(value) else round(value, 6)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


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


def kpi(label: str, value: Any, unit: str = "", sub: str = "", tone: str = "cyan") -> dict:
    return {"label": label, "value": value, "unit": unit, "sub": sub, "tone": tone}


def table(table_id: str, title: str, columns: list[str], rows: list[list[Any]]) -> dict:
    return {"id": table_id, "title": title, "columns": columns, "rows": rows}


def chart(
    chart_id: str, title: str, data: list[dict], layout: dict | None = None, wide: bool = False
) -> dict:
    base = {"margin": {"l": 60, "r": 20, "t": 10, "b": 50}, "height": 320, "bargap": 0.25}
    base.update(layout or {})
    return {"id": chart_id, "title": title, "wide": wide, "figure": {"data": data, "layout": base}}


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


def envelope(
    kind: str,
    *,
    status: str,
    sense: str,
    objective: float | None,
    objective_label: str,
    baseline: dict | None = None,
    kpis: list[dict] | None = None,
    insights: list[str] | None = None,
    tables: list[dict] | None = None,
    charts: list[dict] | None = None,
    solver: dict | None = None,
) -> dict:
    return clean(
        {
            "kind": kind,
            "status": status,
            "sense": sense,
            "objective": objective,
            "objective_label": objective_label,
            "baseline": baseline,
            "kpis": kpis or [],
            "insights": insights or [],
            "tables": tables or [],
            "charts": charts or [],
            "solver": solver or {},
        }
    )


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


def fmt(x: float, digits: int = 2) -> str:
    return f"{x:,.{digits}f}"
