"""The shape of a planner's result: KPIs, insights, tables and charts.

One renderer on the dashboard draws any result with this shape, so the planner
needs no page-specific code:

    {kind, status, sense, objective, objective_label, baseline, kpis,
     insights, tables, charts, solver}
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

CYAN, VIOLET, GREEN, AMBER, RED, GREY = "#22D3EE", "#A78BFA", "#10E39A", "#FFC857", "#FF4D6D", "#64748B"


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


def fmt(x: float, digits: int = 2) -> str:
    return f"{x:,.{digits}f}"
