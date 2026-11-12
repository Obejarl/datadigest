"""One numeric column at a time: moments, robust measures, normality tests and distribution fits."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from datadigest.core.profile import _num
from datadigest.core.stats._common import (
    ALPHA,
    CANDIDATES,
    FIT_MAX,
    MAX_ORDINAL_LEVELS,
    MIN_N,
    POSITIVE_ONLY,
    SEED,
    SHAPIRO_MAX,
    TRIM,
    _p,
    _try,
)


def _mode(values: pd.Series):
    counts = values.round(6).value_counts()
    if counts.empty or counts.iloc[0] < 2:
        return None  # every value is different: no meaningful mode
    return _num(counts.index[0])


def _normality(x: np.ndarray) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    small = x if len(x) <= SHAPIRO_MAX else rng.choice(x, SHAPIRO_MAX, replace=False)
    shapiro = _try(stats.shapiro, small)
    k2 = _try(stats.normaltest, x)
    jb = _try(stats.jarque_bera, x)
    tests = {
        "shapiro": {"stat": _num(shapiro.statistic), "p": _p(shapiro.pvalue)} if shapiro else None,
        "dagostino": {"stat": _num(k2.statistic), "p": _p(k2.pvalue)} if k2 else None,
        "jarque_bera": {"stat": _num(jb.statistic), "p": _p(jb.pvalue)} if jb else None,
    }
    ps = [t["p"] for t in tests.values() if t and t["p"] is not None]
    # Reject normality only when the tests agree; one grumpy test on a big sample means little.
    tests["rejected"] = bool(ps) and sum(p < ALPHA for p in ps) >= max(2, math.ceil(len(ps) / 2 + 0.01))
    return tests


def _fits(x: np.ndarray) -> list[dict[str, Any]]:
    """Kolmogorov-Smirnov distance to common distributions fitted by maximum likelihood.

    The p-values are optimistic because the parameters were estimated from the same data (the
    Lilliefors problem), so the distance D is what to compare; the p-value only warns.
    """
    rng = np.random.default_rng(SEED)
    sample = x if len(x) <= FIT_MAX else rng.choice(x, FIT_MAX, replace=False)
    results = []
    for name in CANDIDATES:
        if name in POSITIVE_ONLY and sample.min() <= 0:
            continue
        if name == "expon" and sample.min() < 0:
            continue
        dist = getattr(stats, name)
        params = (
            _try(dist.fit, sample, floc=0) if name in POSITIVE_ONLY | {"expon"} else _try(dist.fit, sample)
        )
        if params is None:
            continue
        ks = _try(stats.kstest, sample, dist.cdf, args=params)
        logpdf = _try(dist.logpdf, sample, *params)
        if ks is None or logpdf is None or not np.isfinite(logpdf).all():
            continue
        results.append(
            {
                "dist": name,
                "ks_stat": _num(ks.statistic),
                "ks_p": _p(ks.pvalue),
                "aic": _num(2 * len(params) - 2 * float(logpdf.sum())),
            }
        )
    return sorted(results, key=lambda r: r["ks_stat"])


def _shape(skew: float | None, kurt: float | None, normal_rejected: bool, unique: int) -> str:
    if unique <= 2:
        return "binary"
    if unique <= 10:
        return "discrete"
    if not normal_rejected:
        return "approximately normal"
    if skew is not None and skew >= 1:
        return "right-skewed"
    if skew is not None and skew <= -1:
        return "left-skewed"
    if kurt is not None and kurt > 3:
        return "heavy-tailed"
    if kurt is not None and kurt < -1:
        return "flat (light-tailed)"
    return "not normal"


def _distribution(name: str, s: pd.Series) -> dict[str, Any] | None:
    x = s.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < MIN_N:
        return None
    mean, std = float(x.mean()), float(x.std(ddof=1))
    q1, median, q3 = np.percentile(x, [25, 50, 75])
    sem = std / math.sqrt(n)
    t_crit = float(stats.t.ppf(0.975, n - 1))
    skew = _try(stats.skew, x, bias=False)
    kurt = _try(stats.kurtosis, x, bias=False)
    normality = _normality(x) if std > 0 else None
    unique = int(len(np.unique(x)))
    discrete = unique <= MAX_ORDINAL_LEVELS
    fits = [] if (std == 0 or discrete) else _fits(x)
    mad = float(np.median(np.abs(x - median)))
    p1, p5, p95, p99 = np.percentile(x, [1, 5, 95, 99])
    return {
        "name": name,
        "n": n,
        "mean": _num(mean),
        "median": _num(median),
        "mode": _mode(pd.Series(x)),
        "variance": _num(std**2),
        "std": _num(std),
        "cv": _num(std / abs(mean)) if mean else None,  # coefficient of variation
        "sem": _num(sem),
        "ci95_mean": [_num(mean - t_crit * sem), _num(mean + t_crit * sem)],
        "min": _num(x.min()),
        "max": _num(x.max()),
        "range": _num(x.max() - x.min()),
        "iqr": _num(q3 - q1),
        "mad": _num(mad),  # median absolute deviation
        "robust_cv": _num(1.4826 * mad / abs(median)) if median else None,
        "p1": _num(p1),
        "p5": _num(p5),
        "p95": _num(p95),
        "p99": _num(p99),
        "trimmed_mean": _num(stats.trim_mean(x, TRIM)),
        "skew": _num(skew),
        "kurtosis": _num(kurt),  # excess kurtosis: 0 for a normal distribution
        "unique": unique,
        "normality": normality,
        "fits": fits,
        "best_fit": fits[0]["dist"] if fits else None,
        "shape": _shape(_num(skew), _num(kurt), bool(normality and normality["rejected"]), unique),
    }
