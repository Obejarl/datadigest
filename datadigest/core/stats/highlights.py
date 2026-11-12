"""What stands out, in plain sentences.

The tables hold dozens of test results, and a reader who is not a statistician tends to treat
every small p-value as a finding. The highlights say what is worth looking at (relations that
are both significant *and* large), what to be careful with (results that pass a test but are
tiny, statistics that depend on a few outliers), and nothing else.
"""

from __future__ import annotations

from typing import Any

from datadigest.core.stats._common import ALPHA

TOP = 3
LARGE = {"strong", "very strong", "large"}
NOTABLE = LARGE | {"moderate", "medium"}
SMALL = {"negligible", "weak", "small"}


def _significant(row: dict[str, Any]) -> bool:
    return row.get("p_adj") is not None and row["p_adj"] < ALPHA


def _item(kind: str, text: str) -> dict[str, str]:
    """kind: "finding" (worth a look), "caution" (easy to misread) or "info"."""
    return {"kind": kind, "text": text}


def _list(names: list[str], limit: int = TOP) -> str:
    shown = ", ".join(names[:limit])
    return f"{shown} and {len(names) - limit} more" if len(names) > limit else shown


def tests_run(associations: dict[str, list[dict[str, Any]]]) -> int:
    return sum(1 for rows in associations.values() for r in rows if r.get("p_adj") is not None)


def build_highlights(
    distributions: list[dict[str, Any]],
    associations: dict[str, list[dict[str, Any]]],
    consistency: dict[str, Any],
    sensitivity: dict[str, Any],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    # ---- relations that are both significant and large
    numeric = [r for r in associations["numeric"] if _significant(r) and r["strength"] in LARGE]
    for r in numeric[:TOP]:
        rho = r["spearman"] if r["spearman"] is not None else r["pearson"]
        direction = "rise and fall together" if (rho or 0) >= 0 else "move in opposite directions"
        out.append(
            _item("finding", f"{r['a']} and {r['b']} {direction} ({r['strength']} relation, ρ = {rho:.2f}).")
        )
    categorical = [
        r
        for r in associations["categorical"]
        if _significant(r) and r["strength"] in NOTABLE and r.get("reliable", True)
    ]
    for r in categorical[:TOP]:
        out.append(
            _item(
                "finding",
                f"{r['a']} and {r['b']} are related: knowing one tells you something about the other "
                f"({r['strength']} association, Cramér's V = {r['cramers_v'] or 0:.2f}).",
            )
        )
    groups = [r for r in associations["by_group"] if _significant(r) and r["effect"] in NOTABLE]
    for r in groups[:TOP]:
        explained = (r["eta_squared"] or 0) * 100
        out.append(
            _item(
                "finding",
                f"{r['numeric']} differs between the groups of {r['group']} "
                f"({r['effect']} effect: the grouping explains {explained:.0f}% of its variation).",
            )
        )
    if not out:
        out.append(_item("info", "No strong relation between columns was found."))

    # ---- significant but small: the classic misreading
    tiny = [
        r
        for rows in associations.values()
        for r in rows
        if _significant(r) and (r.get("strength") or r.get("effect")) in SMALL
    ]
    if tiny:
        out.append(
            _item(
                "caution",
                f"{len(tiny)} result(s) pass the significance test but are small in size. With many rows "
                "almost any difference is significant; a small effect is rarely worth acting on.",
            )
        )
    if numeric or categorical or groups:
        out.append(
            _item(
                "caution",
                "A relation is not a cause: both columns may follow a third one "
                "(season, region, customer type).",
            )
        )

    # ---- which numbers to trust
    not_normal = [d["name"] for d in distributions if (d.get("normality") or {}).get("rejected")]
    if not_normal:
        out.append(
            _item(
                "info",
                f"{len(not_normal)} of {len(distributions)} numeric column(s) are clearly not bell-shaped "
                f"({_list(not_normal)}): describe them with the median, not the mean.",
            )
        )
    sensitive = [c for c in sensitivity["columns"] if c["robustness"] == "sensitive"]
    if sensitive:
        worst = max(sensitive, key=lambda c: abs(c["mean_shift_pct"] or 0))
        shift = abs(worst["mean_shift_pct"] or 0)
        out.append(
            _item(
                "caution",
                f"The average of {_list([c['name'] for c in sensitive])} depends on a few extreme values "
                f"(the mean of {worst['name']} moves by {shift:.0f}% without them). "
                "Check those rows before quoting an average.",
            )
        )
    fragile = [r for r in sensitivity["correlations"] if r["fragile"]]
    if fragile:
        pairs = [f"{r['a']} × {r['b']}" for r in fragile]
        out.append(
            _item(
                "caution",
                f"{len(fragile)} correlation(s) change a lot once the outliers are left out "
                f"({_list(pairs)}): they describe a few rows, not the data as a whole.",
            )
        )

    # ---- how consistent the file is
    graded = [c for c in consistency["columns"] if c["degree"] is not None]
    weakest = min(graded, key=lambda c: c["degree"], default=None)
    if weakest is not None and weakest["degree"] < 90:
        out.append(
            _item(
                "info",
                f"Consistency is grade {consistency['grade']} ({consistency['score']:.0f} / 100); "
                f"the weakest column is {weakest['name']} ({weakest['degree']:.0f}).",
            )
        )
    return out
