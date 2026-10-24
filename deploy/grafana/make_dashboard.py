"""Generate the Grafana dashboard JSON (kept as code so it can be reviewed and changed).

python deploy/grafana/make_dashboard.py
"""

import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
OUT = Path(__file__).parent / "dashboards" / "datadigest.json"


def stat(title, expr, x, color="text", unit="none"):
    return {
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": 4, "w": 6, "x": x, "y": 0},
        "targets": [{"refId": "A", "expr": expr, "datasource": DS}],
        "fieldConfig": {
            "defaults": {"unit": unit, "color": {"mode": "fixed", "fixedColor": color}},
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "area"},
    }


def series(title, targets, x, y, unit="none", w=12):
    return {
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": 8, "w": w, "x": x, "y": y},
        "targets": [
            {"refId": chr(65 + i), "expr": expr, "legendFormat": legend, "datasource": DS}
            for i, (expr, legend) in enumerate(targets)
        ],
        "fieldConfig": {
            "defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 12}},
            "overrides": [],
        },
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    }


def p95(metric, by):
    return f"histogram_quantile(0.95, sum by (le, {by}) (rate({metric}_bucket[5m])))"


panels = [
    stat("Jobs done", 'sum(datadigest_jobs_total{status="done"})', 0, "green"),
    stat("Queue: pending", 'sum(datadigest_queue_jobs{state="pending"})', 6, "blue"),
    stat("Queue: in flight", 'sum(datadigest_queue_jobs{state="in_flight"})', 12, "purple"),
    stat("Dead letters", 'sum(datadigest_queue_jobs{state="dead"})', 18, "red"),
    series(
        "API requests per second by route",
        [("sum by (route) (rate(datadigest_http_requests_total[1m]))", "{{route}}")],
        0,
        4,
        "reqps",
    ),
    series(
        "API latency p95 by route",
        [(p95("datadigest_http_request_duration_seconds", "route"), "{{route}}")],
        12,
        4,
        "s",
    ),
    series(
        "Jobs per minute by kind and outcome",
        [("60 * sum by (kind, status) (rate(datadigest_jobs_total[5m]))", "{{kind}} {{status}}")],
        0,
        12,
    ),
    series(
        "Job duration p95 and queue wait p95",
        [
            (p95("datadigest_job_duration_seconds", "kind"), "work: {{kind}}"),
            (p95("datadigest_job_queue_wait_seconds", "kind"), "wait: {{kind}}"),
        ],
        12,
        12,
        "s",
    ),
    series(
        "Reliability: retries, dead letters, crashes, backoffs",
        [
            ("sum(increase(datadigest_jobs_requeued_total[5m]))", "requeued"),
            ("sum(increase(datadigest_jobs_dead_total[5m]))", "dead-lettered"),
            ("sum(increase(datadigest_job_crashes_total[5m]))", "handler crashes"),
            ("sum(increase(datadigest_worker_backoffs_total[5m]))", "waits for Redis/PostgreSQL"),
        ],
        0,
        20,
    ),
    series(
        "Datasets and optimization runs by status",
        [
            ("sum by (status) (datadigest_datasets)", "datasets {{status}}"),
            ("sum by (status) (datadigest_optimizations)", "runs {{status}}"),
        ],
        12,
        20,
    ),
]

dashboard = {
    "uid": "datadigest",
    "title": "DataDigest",
    "tags": ["datadigest"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "panels": [{**p, "id": i + 1} for i, p in enumerate(panels)],
}

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(panels)} panels)")
