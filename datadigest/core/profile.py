"""Compute a JSON-serializable profile of a DataFrame.

The profile is the single source of truth: the API stores it, and both the
dashboard and the HTML report are rendered from it.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from datadigest.core.loader import LoadedTable

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
)
BOOLEAN_WORDS = {"true", "false", "yes", "no", "evet", "hayır", "hayir", "y", "n"}
TOP_N = 10
MAX_CORRELATION_COLUMNS = 20

HIGH_MISSING_PCT = 20.0
HIGH_CORRELATION = 0.9
HIGH_SKEW = 2.0
HIGH_OUTLIER_PCT = 5.0


def _num(value: Any) -> float | int | None:
    """numpy scalars and NaN are not JSON-serializable; normalize them."""
    if value is None:
        return None
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    value = float(value)
    return None if math.isnan(value) or math.isinf(value) else round(value, 6)


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def _parse_dates(series: pd.Series) -> pd.Series | None:
    """Return the series parsed as datetimes if one known format matches >= 90% of values."""
    values = series.dropna().astype(str).str.strip()
    if values.empty or not values.str.contains(r"\d[-./]\d", regex=True).all():
        return None
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(values, format=fmt, errors="coerce")
        if parsed.notna().mean() >= 0.9:
            return pd.to_datetime(series.astype("string").str.strip(), format=fmt, errors="coerce")
    return None


def infer_kind(series: pd.Series) -> tuple[str, pd.Series]:
    """Classify a column and return it converted to the matching dtype."""
    if pd.api.types.is_bool_dtype(series):
        return "boolean", series
    if pd.api.types.is_numeric_dtype(series):
        return "numeric", series
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime", series

    non_null = series.dropna()
    if non_null.empty:
        return "categorical", series
    lowered = set(non_null.astype(str).str.strip().str.lower().unique())
    if lowered <= BOOLEAN_WORDS and len(lowered) <= 2:
        return "boolean", series

    parsed = _parse_dates(series)
    if parsed is not None:
        return "datetime", parsed

    unique = non_null.nunique()
    if unique <= 50 or unique / len(non_null) <= 0.5:
        return "categorical", series
    return "text", series


def _numeric_stats(s: pd.Series) -> dict[str, Any]:
    s = s.dropna().astype(float)
    if s.empty:
        return {}
    q1, median, q3 = s.quantile([0.25, 0.5, 0.75])
    iqr = q3 - q1
    outliers = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0
    bins = int(min(30, max(5, math.sqrt(len(s)))))
    counts, edges = np.histogram(s, bins=bins)
    return {
        "mean": _num(s.mean()),
        "std": _num(s.std()),
        "min": _num(s.min()),
        "p25": _num(q1),
        "median": _num(median),
        "p75": _num(q3),
        "max": _num(s.max()),
        "skew": _num(s.skew()) if len(s) > 2 else None,
        "zeros": int((s == 0).sum()),
        "outliers": outliers,
        "outliers_pct": _pct(outliers, len(s)),
        "histogram": {"counts": counts.tolist(), "edges": [_num(e) for e in edges]},
    }


def _top_values(s: pd.Series) -> dict[str, Any]:
    counts = s.dropna().astype(str).value_counts()
    top = counts.head(TOP_N)
    return {
        "top": [{"value": str(k), "count": int(v)} for k, v in top.items()],
        "other_count": int(counts.iloc[TOP_N:].sum()),
    }


def _datetime_stats(s: pd.Series) -> dict[str, Any]:
    s = s.dropna()
    if s.empty:
        return {}
    span_days = (s.max() - s.min()).days
    freq, fmt = ("M", "%Y-%m") if span_days > 60 else ("D", "%Y-%m-%d")
    counts = s.dt.to_period(freq).value_counts().sort_index()
    return {
        "min": s.min().isoformat(),
        "max": s.max().isoformat(),
        "span_days": span_days,
        "timeline": {
            "freq": freq,
            "labels": [p.strftime(fmt) for p in counts.index],
            "counts": counts.astype(int).tolist(),
        },
    }


def _text_stats(s: pd.Series) -> dict[str, Any]:
    lengths = s.dropna().astype(str).str.len()
    return {
        "avg_length": _num(lengths.mean()),
        "max_length": _num(lengths.max()),
        "examples": s.dropna().astype(str).head(3).tolist(),
    }


def profile_column(name: str, raw: pd.Series) -> tuple[dict[str, Any], pd.Series]:
    kind, series = infer_kind(raw)
    rows = len(series)
    missing = int(series.isna().sum())
    unique = int(series.nunique(dropna=True))
    column: dict[str, Any] = {
        "name": name,
        "kind": kind,
        "dtype": str(raw.dtype),
        "missing": missing,
        "missing_pct": _pct(missing, rows),
        "unique": unique,
        "unique_pct": _pct(unique, rows - missing),
    }
    if kind == "numeric":
        column.update(_numeric_stats(series))
    elif kind in ("categorical", "boolean"):
        column.update(_top_values(series))
    elif kind == "datetime":
        column.update(_datetime_stats(series))
    else:
        column.update(_text_stats(series))
    return column, series


def _correlations(numeric: pd.DataFrame) -> dict[str, Any] | None:
    numeric = numeric.loc[:, numeric.std(numeric_only=True) > 0]
    if numeric.shape[1] < 2:
        return None
    numeric = numeric.iloc[:, :MAX_CORRELATION_COLUMNS]
    matrix = numeric.corr(method="pearson")
    return {
        "columns": list(matrix.columns),
        "matrix": [[_num(v) for v in row] for row in matrix.to_numpy()],
    }


def _looks_like_id(c: dict) -> bool:
    # Unique floats (prices, incomes) and unique free text (comments) are normal, not IDs.
    if c["kind"] == "numeric":
        return "int" in c["dtype"]
    return c["kind"] == "text" and not any(" " in ex for ex in c.get("examples", []))


def _warnings(columns: list[dict], correlations: dict | None, duplicates: int, rows: int):
    warnings = []

    def add(kind: str, message: str, columns: list[str] | None = None):
        warnings.append({"type": kind, "columns": columns or [], "message": message})

    if duplicates:
        add("duplicates", f"{duplicates} duplicate rows ({_pct(duplicates, rows)}%)")
    for c in columns:
        name = c["name"]
        if c["missing_pct"] >= HIGH_MISSING_PCT:
            add("high_missing", f"'{name}' is {c['missing_pct']}% missing", [name])
        if c["unique"] <= 1:
            add("constant", f"'{name}' has a single value; it carries no information", [name])
        elif c["unique"] == rows - c["missing"] and rows > 10 and _looks_like_id(c):
            add("unique_id", f"'{name}' is unique on every row; likely an identifier", [name])
        if c["kind"] == "numeric":
            if c.get("skew") is not None and abs(c["skew"]) >= HIGH_SKEW:
                add("skewed", f"'{name}' is highly skewed (skew={c['skew']:.2f})", [name])
            if c.get("outliers_pct", 0) >= HIGH_OUTLIER_PCT:
                add("outliers", f"'{name}' has {c['outliers_pct']}% outliers (IQR rule)", [name])

    if correlations:
        cols, matrix = correlations["columns"], correlations["matrix"]
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                r = matrix[i][j]
                if r is not None and abs(r) >= HIGH_CORRELATION:
                    add(
                        "high_correlation",
                        f"'{cols[i]}' and '{cols[j]}' are highly correlated (r={r:.2f})",
                        [cols[i], cols[j]],
                    )
    return warnings


def build_profile(table: LoadedTable) -> dict[str, Any]:
    df = table.df
    rows = len(df)
    columns, converted = [], {}
    for name in df.columns:
        column, series = profile_column(name, df[name])
        columns.append(column)
        converted[name] = series

    numeric_names = [c["name"] for c in columns if c["kind"] == "numeric"]
    correlations = _correlations(pd.DataFrame({n: converted[n] for n in numeric_names}))
    duplicates = int(df.duplicated().sum())
    missing_cells = int(df.isna().sum().sum())
    kinds: dict[str, int] = {}
    for c in columns:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1

    return {
        "summary": {
            "rows": rows,
            "columns": len(columns),
            "missing_cells": missing_cells,
            "missing_cells_pct": _pct(missing_cells, rows * len(columns)),
            "duplicate_rows": duplicates,
            "memory_bytes": int(df.memory_usage(deep=True).sum()),
            "kinds": kinds,
            "encoding": table.encoding,
            "delimiter": table.delimiter,
            "truncated": table.truncated,
        },
        "columns": columns,
        "correlations": correlations,
        "warnings": _warnings(columns, correlations, duplicates, rows),
    }
