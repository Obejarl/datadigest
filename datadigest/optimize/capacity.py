"""Capacity planning for DataDigest's own workers with queueing theory (M/M/c).

Jobs arrive at rate lambda, each worker finishes them at rate mu = 1 / service
time, and c workers share one queue. Erlang C gives the probability that a job
has to wait; from it follow the mean wait Wq, utilisation rho and a cost per
hour that trades worker cost against waiting cost:

    a   = lambda / mu                 offered load (busy workers on average)
    rho = a / c                       utilisation, must be < 1
    C   = ErlangC(c, a)               P(job waits)
    Wq  = C / (c*mu - lambda)         mean wait in the queue
    cost/h = c * worker_cost + lambda * Wq * wait_cost

The answer is turned into Kubernetes settings (HPA min/max replicas).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from datadigest.optimize.common import AMBER, CYAN, GREEN, RED, VIOLET, chart, envelope, fmt, kpi, table

KIND = "capacity"
MAX_UTILISATION = 0.85  # beyond this, waits explode with any burst


@dataclass
class CapacityInputs:
    arrival_per_min: float = 6.0
    service_seconds: float = 4.0
    target_wait_seconds: float = 5.0
    worker_cost_per_hour: float = 0.05
    wait_cost_per_hour: float = 20.0
    peak_factor: float = 2.0
    max_workers: int = 20


def erlang_c(c: int, a: float) -> float:
    """P(wait) in an M/M/c queue, via the numerically stable Erlang B recursion."""
    if a <= 0:
        return 0.0
    if a >= c:
        return 1.0
    b = 1.0
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    rho = a / c
    return b / (1 - rho * (1 - b))


def metrics(c: int, lam: float, mu: float, target: float) -> dict:
    """lam and mu are per second."""
    a = lam / mu
    rho = a / c
    if rho >= 1:
        return {"workers": c, "stable": False, "utilisation": rho}
    p_wait = erlang_c(c, a)
    wq = p_wait / (c * mu - lam)
    return {
        "workers": c,
        "stable": True,
        "utilisation": rho,
        "p_wait": p_wait,
        "wait_s": wq,
        "time_in_system_s": wq + 1 / mu,
        "queue_length": lam * wq,
        "p_wait_over_target": p_wait * math.exp(-(c * mu - lam) * target),
        "capacity_per_min": 60 * c * mu,
    }


def _recommend(rows: list[dict], target: float) -> dict | None:
    return next(
        (r for r in rows if r["stable"] and r["wait_s"] <= target and r["utilisation"] <= MAX_UTILISATION),
        None,
    )


def plan(inputs: CapacityInputs, measured: dict | None = None, uses_measured: bool = False) -> dict:
    lam = inputs.arrival_per_min / 60
    mu = 1 / inputs.service_seconds
    target = inputs.target_wait_seconds
    cs = range(1, inputs.max_workers + 1)
    rows = [metrics(c, lam, mu, target) for c in cs]
    for r in rows:
        if r["stable"]:
            r["cost_per_hour"] = (
                r["workers"] * inputs.worker_cost_per_hour + lam * r["wait_s"] * inputs.wait_cost_per_hour
            )
    peak_rows = [metrics(c, lam * inputs.peak_factor, mu, target) for c in cs]

    stable = [r for r in rows if r["stable"]]
    rec = _recommend(rows, target)
    rec_peak = _recommend(peak_rows, target)
    cheapest = min(stable, key=lambda r: r["cost_per_hour"]) if stable else None
    min_stable = stable[0]["workers"] if stable else None
    load = lam / mu

    insights = [
        f"Offered load is {load:.2f} busy workers on average ({inputs.arrival_per_min:g} jobs/min × "
        f"{inputs.service_seconds:g} s each), so at least {math.floor(load) + 1} worker(s) "
        "are needed just to keep up.",
    ]
    if rec:
        insights.append(
            f"{rec['workers']} worker(s) keep the mean wait at {rec['wait_s']:.2f} s (target {target:g} s) "
            f"with {100 * rec['utilisation']:.0f}% utilisation; "
            f"{100 * rec['p_wait_over_target']:.1f}% of jobs would wait longer than the target."
        )
    else:
        insights.append(
            f"No worker count up to {inputs.max_workers} meets a {target:g} s target under "
            f"{100 * MAX_UTILISATION:.0f}% utilisation. Raise max workers or make jobs faster."
        )
    if cheapest:
        insights.append(
            f"Cheapest overall: {cheapest['workers']} worker(s) at {fmt(cheapest['cost_per_hour'])}/h, "
            f"balancing {fmt(inputs.worker_cost_per_hour)}/h per worker against "
            f"{fmt(inputs.wait_cost_per_hour)}/h of waiting."
        )
    if rec_peak:
        insights.append(
            f"At a {inputs.peak_factor:g}× peak ({inputs.arrival_per_min * inputs.peak_factor:g} jobs/min) "
            f"you need {rec_peak['workers']} worker(s): use that as the HPA maxReplicas."
        )
    if rec and rec["workers"] > 1:
        prev = rows[rec["workers"] - 2]
        if prev["stable"]:
            insights.append(
                f"Going from {prev['workers']} to {rec['workers']} workers cuts the mean wait from "
                f"{prev['wait_s']:.2f} s to {rec['wait_s']:.2f} s: queueing delay is very non-linear "
                "near full utilisation."
            )
    if uses_measured and measured and measured.get("service_samples"):
        cv = measured.get("service_cv")
        note = ""
        if cv is not None:
            note = (
                " Service times vary less than the model assumes, so real waits should be shorter."
                if cv < 0.8
                else " Service times vary more than the model assumes, so real waits may be longer: "
                "keep headroom."
                if cv > 1.2
                else ""
            )
        insights.append(
            f"Arrival rate and service time are measured from {measured['service_samples']} completed "
            f"jobs (service-time CV {cv:.2f}). M/M/c assumes random arrivals and exponential service "
            f"(CV 1).{note}"
            if cv is not None
            else f"Service time is measured from {measured['service_samples']} completed jobs."
        )

    hpa = {
        "minReplicas": rec["workers"] if rec else min_stable or 1,
        "maxReplicas": max(
            rec_peak["workers"] if rec_peak else inputs.max_workers, rec["workers"] if rec else 1
        ),
    }

    x = [r["workers"] for r in stable]
    charts = [
        chart(
            "wait",
            "Mean wait in queue vs workers",
            [
                {
                    "type": "scatter",
                    "mode": "lines+markers",
                    "x": x,
                    "y": [max(r["wait_s"], 1e-6) for r in stable],  # log axis: keep ~0 waits on the chart
                    "line": {"color": CYAN},
                    "name": "normal load",
                    "hovertemplate": "%{x} workers: %{y:.2f} s<extra></extra>",
                },
                {
                    "type": "scatter",
                    "mode": "lines+markers",
                    "x": [r["workers"] for r in peak_rows if r["stable"]],
                    "y": [max(r["wait_s"], 1e-6) for r in peak_rows if r["stable"]],
                    "line": {"color": VIOLET, "dash": "dot"},
                    "name": f"{inputs.peak_factor:g}× peak",
                    "hovertemplate": "%{x} workers: %{y:.2f} s<extra></extra>",
                },
            ],
            {
                "yaxis": {"type": "log", "title": {"text": "seconds (log)"}},
                "xaxis": {"title": {"text": "workers"}, "dtick": 1},
                "legend": {"orientation": "h", "y": 1.12},
                "shapes": [
                    {
                        "type": "line",
                        "xref": "paper",
                        "x0": 0,
                        "x1": 1,
                        "y0": target,
                        "y1": target,
                        "line": {"color": RED, "dash": "dot"},
                    }
                ],
            },
        ),
        chart(
            "cost",
            "Cost per hour vs workers",
            [
                {
                    "type": "bar",
                    "x": x,
                    "y": [r["cost_per_hour"] for r in stable],
                    "marker": {
                        "color": [
                            GREEN if cheapest and r["workers"] == cheapest["workers"] else AMBER
                            for r in stable
                        ]
                    },
                    "hovertemplate": "%{x} workers: %{y:,.2f}/h<extra></extra>",
                }
            ],
            {"xaxis": {"title": {"text": "workers"}, "dtick": 1}},
        ),
        chart(
            "util",
            "Utilisation vs workers",
            [
                {
                    "type": "bar",
                    "x": [r["workers"] for r in rows],
                    "y": [min(100, 100 * r["utilisation"]) for r in rows],
                    "marker": {
                        "color": [
                            RED
                            if r["utilisation"] >= 1
                            else AMBER
                            if r["utilisation"] > MAX_UTILISATION
                            else CYAN
                            for r in rows
                        ]
                    },
                    "hovertemplate": "%{x} workers: %{y:.0f}%<extra></extra>",
                }
            ],
            {
                "xaxis": {"title": {"text": "workers"}, "dtick": 1},
                "yaxis": {"ticksuffix": "%", "range": [0, 105]},
            },
        ),
    ]
    table_rows = [
        [
            r["workers"],
            100 * r["utilisation"],
            r.get("p_wait"),
            r.get("wait_s"),
            r.get("time_in_system_s"),
            r.get("capacity_per_min"),
            r.get("cost_per_hour"),
            "recommended"
            if rec and r["workers"] == rec["workers"]
            else "cheapest"
            if cheapest and r["workers"] == cheapest["workers"]
            else ("" if r["stable"] else "unstable"),
        ]
        for r in rows[: max(8, (rec_peak or rec or {"workers": 8})["workers"] + 2)]
    ]
    result = envelope(
        KIND,
        status="optimal" if rec else "infeasible",
        sense="min",
        objective=rec["workers"] if rec else None,
        objective_label="Recommended workers",
        kpis=[
            kpi(
                "Recommended workers",
                rec["workers"] if rec else "–",
                sub=f"meets {target:g} s mean wait",
                tone="cyan",
            ),
            kpi(
                "Expected wait",
                f"{rec['wait_s']:.2f}" if rec else "–",
                "s",
                sub=f"utilisation {100 * rec['utilisation']:.0f}%" if rec else "",
                tone="green",
            ),
            kpi(
                "Cost-optimal",
                cheapest["workers"] if cheapest else "–",
                sub=f"{fmt(cheapest['cost_per_hour'])}/h" if cheapest else "",
                tone="amber",
            ),
            kpi("Peak (HPA max)", hpa["maxReplicas"], sub=f"at {inputs.peak_factor:g}× load", tone="violet"),
        ],
        insights=insights,
        tables=[
            table(
                "workers",
                "Workers compared",
                [
                    "Workers",
                    "Utilisation %",
                    "P(wait)",
                    "Mean wait s",
                    "Time in system s",
                    "Capacity jobs/min",
                    "Cost per hour",
                    "Note",
                ],
                table_rows,
            )
        ],
        charts=charts,
        solver={"name": "M/M/c (Erlang C)", "variables": inputs.max_workers, "constraints": 2, "seconds": 0},
    )
    result["hpa"] = hpa
    result["inputs"] = asdict(inputs)
    result["measured"] = measured or {}
    return result
