"""Degrees of consistency: completeness, validity, formats, label variants, keys and Cronbach's alpha."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
from scipy import stats

from datadigest.core.profile import GRADES, _num
from datadigest.core.stats._common import ALPHA_LABELS, MAX_NUMERIC, MIN_N, _try


def _pattern(value: str) -> str:
    """The 'shape' of a string: digits become 9, letters a/A, runs are kept so 2024-01-05 is 9999-99-99."""
    return re.sub(r"[A-ZÇĞİÖŞÜ]", "A", re.sub(r"[a-zçğıöşü]", "a", re.sub(r"\d", "9", value)))


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _format_consistency(values: pd.Series) -> dict[str, Any] | None:
    strings = values.dropna().astype(str)
    if len(strings) < MIN_N:
        return None
    patterns = strings.map(_pattern).value_counts()
    return {
        "share": _num(float(patterns.iloc[0]) / len(strings)),
        "dominant": str(patterns.index[0])[:40],
        "patterns": int(len(patterns)),
    }


def _label_variants(values: pd.Series) -> dict[str, Any]:
    """Different spellings of what is probably the same label (case, spaces)."""
    strings = values.dropna().astype(str)
    groups: dict[str, set[str]] = {}
    for v in strings.unique()[:5_000]:
        groups.setdefault(_normalized(v), set()).add(v)
    clashes = [sorted(v) for v in groups.values() if len(v) > 1]
    return {"groups": len(clashes), "examples": [" / ".join(repr(x) for x in c[:3]) for c in clashes[:3]]}


def _key_conflicts(frame: pd.DataFrame, kinds: dict[str, str], columns: list[dict]) -> dict[str, Any] | None:
    """Rows that share an ID but disagree on other columns: the same entity recorded two ways."""
    for c in columns:
        key = c["name"]
        if kinds.get(key) != "numeric" or "int" not in c.get("dtype", "") or c.get("unique_pct", 0) < 80:
            continue
        grouped = frame.groupby(key, dropna=True)
        sizes = grouped.size()
        repeated = sizes[sizes > 1].index
        if len(repeated) == 0:
            return {"key": key, "repeated_keys": 0, "conflicting_keys": 0}
        sub = frame[frame[key].isin(repeated)]
        distinct = sub.groupby(key).nunique(dropna=True)
        conflicting = int((distinct > 1).any(axis=1).sum())
        return {"key": key, "repeated_keys": int(len(repeated)), "conflicting_keys": conflicting}
    return None


def cronbach_alpha(items: pd.DataFrame) -> dict[str, Any] | None:
    """Internal consistency of a set of numeric columns (complete rows only).

    Raw alpha uses the covariances; standardized alpha is the same idea after scaling every item,
    so a column in dollars does not drown out a column in units.
    """
    items = items.dropna()
    k = items.shape[1]
    if k < 3 or len(items) < 30:
        return None
    variances = items.var(ddof=1)
    total = items.sum(axis=1).var(ddof=1)
    if total <= 0 or (variances <= 0).any():
        return None
    raw = k / (k - 1) * (1 - variances.sum() / total)
    corr = items.corr().to_numpy()
    mean_r = float((corr.sum() - k) / (k * (k - 1)))
    standardized = k * mean_r / (1 + (k - 1) * mean_r)
    item_stats = []
    for c in items.columns:
        rest = items.drop(columns=c)
        rest_total = rest.sum(axis=1)
        r_it = _try(stats.pearsonr, items[c], rest_total)
        alpha_wo = None
        if rest.shape[1] >= 2 and rest_total.var(ddof=1) > 0:
            alpha_wo = (
                rest.shape[1] / (rest.shape[1] - 1) * (1 - rest.var(ddof=1).sum() / rest_total.var(ddof=1))
            )
        item_stats.append(
            {
                "name": c,
                "item_total_r": _num(r_it.statistic)
                if r_it
                else None,  # corrected: the item is left out of the total
                "alpha_if_deleted": _num(alpha_wo),
            }
        )
    label = "unacceptable" if raw < 0.5 else next(name for t, name in ALPHA_LABELS if raw >= t)
    return {
        "alpha": _num(raw),
        "alpha_standardized": _num(standardized),
        "mean_inter_item_r": _num(mean_r),
        "items": k,
        "n": int(len(items)),
        "label": label,
        "item_stats": item_stats,
        "note": "Meaningful only if the columns measure one thing on similar scales (a survey scale, say).",
    }


def _grade(score: float) -> str:
    return next(letter for threshold, letter in GRADES if score >= threshold)


def _consistency(
    frame: pd.DataFrame,
    raw: pd.DataFrame,
    kinds: dict[str, str],
    columns: list[dict],
    validity: dict[str, float],
    sampled: bool,
    numeric: list[str],
) -> dict[str, Any]:
    out_columns = []
    for c in columns:
        name = c["name"]
        completeness = 1 - c["missing_pct"] / 100
        valid = validity.get(name, 1.0)
        fmt = _format_consistency(raw[name]) if name in raw and kinds.get(name) != "numeric" else None
        parts = [completeness, valid] + ([fmt["share"]] if fmt and fmt["share"] is not None else [])
        entry = {
            "name": name,
            "kind": kinds.get(name),
            "completeness": _num(completeness),
            "validity": _num(valid),  # share of non-empty values that could be read as the column's type
            "uniqueness": _num(c["unique_pct"] / 100),
            "format": fmt,
            "degree": _num(100 * sum(parts) / len(parts)),
        }
        if kinds.get(name) in ("categorical", "text") and name in frame:
            variants = _label_variants(frame[name])
            entry["label_variants"] = variants
            if variants["groups"]:
                entry["degree"] = _num(
                    entry["degree"] * (1 - min(0.5, variants["groups"] / max(1, c["unique"])))
                )
        out_columns.append(entry)

    degrees = [e["degree"] for e in out_columns if e["degree"] is not None]
    overall = sum(degrees) / len(degrees) if degrees else 100.0
    conflicts = None if sampled else _key_conflicts(frame, kinds, columns)
    if conflicts and conflicts["repeated_keys"]:
        overall *= 1 - 0.5 * conflicts["conflicting_keys"] / max(1, conflicts["repeated_keys"])
    items = frame[numeric[:MAX_NUMERIC]] if len(numeric) >= 3 else None
    return {
        "score": round(overall, 1),
        "grade": _grade(overall),
        "columns": out_columns,
        "key_conflicts": conflicts,
        "cronbach": cronbach_alpha(items) if items is not None else None,
    }
