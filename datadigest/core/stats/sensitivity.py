"""How much the statistics depend on the outliers: with/without comparisons and bootstrap intervals."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from datadigest.core.profile import _num
from datadigest.core.stats._common import BOOTSTRAP_ROWS, BOOTSTRAPS, MIN_N, SEED, TRIM, _try


def _iqr_mask(x: pd.Series) -> pd.Series:
    q1, q3 = x.quantile([0.25, 0.75])
    iqr = q3 - q1
    return (x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr) if iqr > 0 else pd.Series(False, index=x.index)


def _pct_change(before: float, after: float) -> float | None:
    return _num(100.0 * (after - before) / abs(before)) if before else None


def _sensitivity(frame: pd.DataFrame, numeric: list[str], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    columns = []
    for c in numeric:
        x = frame[c].dropna()
        if len(x) < MIN_N or x.nunique() < 2:
            continue
        mask = _iqr_mask(x)
        clean = x[~mask]
        sample = (
            x.to_numpy()
            if len(x) <= BOOTSTRAP_ROWS
            else rng.choice(x.to_numpy(), BOOTSTRAP_ROWS, replace=False)
        )
        idx = rng.integers(0, len(sample), size=(BOOTSTRAPS, len(sample)))
        resampled = sample[idx]
        means, medians = resampled.mean(axis=1), np.median(resampled, axis=1)
        winsor = stats.mstats.winsorize(x.to_numpy(), limits=(0.05, 0.05))
        mean_shift = _pct_change(float(x.mean()), float(clean.mean())) if len(clean) >= 2 else None
        std_shift = _pct_change(float(x.std()), float(clean.std())) if len(clean) >= 2 else None
        median_shift = _pct_change(float(x.median()), float(clean.median())) if len(clean) >= 2 else None
        worst = max(abs(v) for v in (mean_shift, std_shift) if v is not None) if mean_shift is not None else 0
        columns.append(
            {
                "name": c,
                "outliers_removed": int(mask.sum()),
                "mean": _num(x.mean()),
                "mean_without_outliers": _num(clean.mean()) if len(clean) else None,
                "mean_shift_pct": mean_shift,
                "median_shift_pct": median_shift,
                "std_shift_pct": std_shift,
                "skew_without_outliers": _num(stats.skew(clean, bias=False)) if len(clean) > 2 else None,
                "winsorized_mean": _num(winsor.mean()),
                "trimmed_mean": _num(stats.trim_mean(x.to_numpy(), TRIM)),
                "bootstrap_mean_ci": [_num(np.percentile(means, 2.5)), _num(np.percentile(means, 97.5))],
                "bootstrap_median_ci": [
                    _num(np.percentile(medians, 2.5)),
                    _num(np.percentile(medians, 97.5)),
                ],
                "bootstrap_rows": int(len(sample)),
                "robustness": "sensitive" if worst >= 10 else "moderate" if worst >= 3 else "robust",
            }
        )
    columns.sort(key=lambda r: -max(abs(r["mean_shift_pct"] or 0), abs(r["std_shift_pct"] or 0)))

    correlations = []
    for r in pairs[:15]:
        pair = frame[[r["a"], r["b"]]].dropna()
        keep = ~(_iqr_mask(pair[r["a"]]) | _iqr_mask(pair[r["b"]]))
        if keep.sum() < MIN_N or pair[keep][r["a"]].nunique() < 2 or pair[keep][r["b"]].nunique() < 2:
            continue
        clean = _try(stats.pearsonr, pair[keep][r["a"]], pair[keep][r["b"]])
        if clean is None or r["pearson"] is None:
            continue
        delta = float(clean.statistic) - r["pearson"]
        correlations.append(
            {
                "a": r["a"],
                "b": r["b"],
                "pearson": r["pearson"],
                "pearson_without_outliers": _num(clean.statistic),
                "delta": _num(delta),
                "rows_dropped": int((~keep).sum()),
                "fragile": abs(delta) >= 0.1 or (r["pearson"] * float(clean.statistic) < 0),
            }
        )
    correlations.sort(key=lambda r: -abs(r["delta"] or 0))
    return {"columns": columns, "correlations": correlations}
