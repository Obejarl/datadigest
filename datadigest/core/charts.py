"""Build Plotly figure specs (plain dicts) from a profile.

We emit JSON specs instead of using the plotly Python package: the browser
already loads plotly.js, so the dashboard and the HTML report draw the exact
same figures from the same data with no extra server dependency.
"""

from __future__ import annotations

from typing import Any

ACCENT = "#4f6bed"
MAX_COLUMN_CHARTS = 30


def _layout(title: str, **extra: Any) -> dict[str, Any]:
    layout = {
        "title": {"text": title, "font": {"size": 14}},
        "margin": {"l": 50, "r": 20, "t": 40, "b": 50},
        "height": 300,
        "bargap": 0.05,
    }
    layout.update(extra)
    return layout


def _chart(chart_id: str, title: str, data: list, layout: dict, column: str | None = None):
    return {"id": chart_id, "title": title, "column": column, "figure": {"data": data, "layout": layout}}


def missing_chart(profile: dict) -> dict | None:
    cols = [c for c in profile["columns"] if c["missing"] > 0]
    if not cols:
        return None
    cols.sort(key=lambda c: c["missing_pct"])
    data = [{
        "type": "bar",
        "orientation": "h",
        "x": [c["missing_pct"] for c in cols],
        "y": [c["name"] for c in cols],
        "marker": {"color": ACCENT},
        "hovertemplate": "%{y}: %{x}%<extra></extra>",
    }]
    layout = _layout("Missing values (%)", height=max(220, 26 * len(cols) + 80),
                     margin={"l": 140, "r": 20, "t": 40, "b": 40})
    return _chart("missing", "Missing values", data, layout)


def _histogram(c: dict) -> dict | None:
    hist = c.get("histogram")
    if not hist:
        return None
    edges = hist["edges"]
    centers = [(a + b) / 2 for a, b in zip(edges[:-1], edges[1:], strict=True)]
    widths = [b - a for a, b in zip(edges[:-1], edges[1:], strict=True)]
    data = [{
        "type": "bar", "x": centers, "y": hist["counts"], "width": widths,
        "marker": {"color": ACCENT},
        "hovertemplate": "%{x}: %{y}<extra></extra>",
    }]
    return _chart(f"col-{c['name']}", c["name"], data, _layout(f"{c['name']} — distribution"), c["name"])


def _top_bar(c: dict) -> dict | None:
    top = list(reversed(c.get("top", [])))
    if not top:
        return None
    data = [{
        "type": "bar", "orientation": "h",
        "x": [t["count"] for t in top], "y": [t["value"] for t in top],
        "marker": {"color": ACCENT},
        "hovertemplate": "%{y}: %{x}<extra></extra>",
    }]
    layout = _layout(f"{c['name']} — top values", margin={"l": 140, "r": 20, "t": 40, "b": 40})
    return _chart(f"col-{c['name']}", c["name"], data, layout, c["name"])


def _timeline(c: dict) -> dict | None:
    timeline = c.get("timeline")
    if not timeline:
        return None
    unit = "month" if timeline["freq"] == "M" else "day"
    data = [{
        "type": "scatter", "mode": "lines+markers",
        "x": timeline["labels"], "y": timeline["counts"],
        "line": {"color": ACCENT},
        "hovertemplate": "%{x}: %{y}<extra></extra>",
    }]
    return _chart(f"col-{c['name']}", c["name"], data, _layout(f"{c['name']} — rows per {unit}"), c["name"])


def correlation_chart(profile: dict) -> dict | None:
    corr = profile.get("correlations")
    if not corr:
        return None
    n = len(corr["columns"])
    data = [{
        "type": "heatmap", "z": corr["matrix"], "x": corr["columns"], "y": corr["columns"],
        "zmin": -1, "zmax": 1, "colorscale": "RdBu", "reversescale": True,
        "hovertemplate": "%{x} × %{y}: %{z:.2f}<extra></extra>",
    }]
    size = max(320, 40 * n + 160)
    layout = _layout("Correlation (Pearson)", height=size,
                     margin={"l": 120, "r": 20, "t": 40, "b": 120})
    return _chart("correlation", "Correlation", data, layout)


COLUMN_CHARTS = {"numeric": _histogram, "categorical": _top_bar, "boolean": _top_bar, "datetime": _timeline}


def build_charts(profile: dict) -> list[dict]:
    charts = [chart for chart in (missing_chart(profile), correlation_chart(profile)) if chart]
    for c in profile["columns"][:MAX_COLUMN_CHARTS]:
        builder = COLUMN_CHARTS.get(c["kind"])
        chart = builder(c) if builder else None
        if chart:
            charts.append(chart)
    return charts
