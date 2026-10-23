"""Render a self-contained HTML report from a profile."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from datadigest.core.charts import build_charts

PLOTLY_JS = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# Column names and values come from user uploads: autoescape is what stops a
# column called "<script>…" from running in the reader's browser.
_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _filesize(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


_env.filters["filesize"] = _filesize


def render_report(profile: dict, title: str) -> str:
    charts = build_charts(profile)
    column_charts = {c["column"]: c for c in charts if c["column"]}
    overview_charts = [c for c in charts if not c["column"]]
    return _env.get_template("report.html.j2").render(
        title=title,
        profile=profile,
        summary=profile["summary"],
        overview_charts=overview_charts,
        column_charts=column_charts,
        charts=charts,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        plotly_js=PLOTLY_JS,
    )
