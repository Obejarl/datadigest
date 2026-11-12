"""Pairs of columns: correlations, chi-square, ordinal measures and group comparisons."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from datadigest.core.profile import _num
from datadigest.core.stats._common import (
    EFFECT_CLIFF,
    EFFECT_D,
    EFFECT_ETA,
    MAX_CATEGORICAL,
    MAX_GROUP_LEVELS,
    MAX_LEVELS,
    MAX_NUMERIC,
    MAX_ORDINAL_LEVELS,
    MAX_PAIR_COLUMNS,
    MIN_GROUP,
    MIN_N,
    SEED,
    STRENGTHS,
    TOP_PAIRS,
    _label,
    _p,
    _try,
    benjamini_hochberg,
)


def _numeric_columns(frame: pd.DataFrame, kinds: dict[str, str]) -> list[str]:
    cols = [c for c in frame.columns if kinds.get(c) == "numeric" and frame[c].dropna().nunique() > 1]
    return cols[:MAX_NUMERIC]


def _numeric_pairs(frame: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    cols = cols[:MAX_PAIR_COLUMNS]
    rows = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            pair = frame[[a, b]].dropna()
            if len(pair) < MIN_N or pair[a].nunique() < 2 or pair[b].nunique() < 2:
                continue
            pearson = _try(stats.pearsonr, pair[a], pair[b])
            spearman = _try(stats.spearmanr, pair[a], pair[b])
            if pearson is None or spearman is None:
                continue
            rows.append(
                {
                    "a": a,
                    "b": b,
                    "n": len(pair),
                    "pearson": _num(pearson.statistic),
                    "spearman": _num(spearman.statistic),
                    "p": _p(pearson.pvalue),
                    "p_spearman": _p(spearman.pvalue),
                }
            )
    adjusted = benjamini_hochberg([r["p"] for r in rows])
    for r, p_adj in zip(rows, adjusted, strict=True):
        r["p_adj"] = p_adj
        strength = max(abs(r["pearson"] or 0), abs(r["spearman"] or 0))
        r["strength"] = _label(strength, STRENGTHS)
        # A big gap between the two says the relation is non-linear or driven by a few extreme points.
        r["nonlinear_hint"] = abs(abs(r["spearman"] or 0) - abs(r["pearson"] or 0)) >= 0.2
    rows.sort(key=lambda r: -max(abs(r["pearson"] or 0), abs(r["spearman"] or 0)))
    rows = rows[:TOP_PAIRS]
    for r in rows[:15]:  # Kendall's tau is the slowest of the three, so only the strongest pairs get it
        pair = frame[[r["a"], r["b"]]].dropna()
        pair = pair if len(pair) <= 5_000 else pair.sample(5_000, random_state=SEED)
        tau = _try(stats.kendalltau, pair[r["a"]], pair[r["b"]])
        r["kendall"] = _num(tau.statistic) if tau else None
    return rows


def _cramers_v(table: np.ndarray, chi2: float) -> float | None:
    """Bias-corrected Cramér's V (Bergsma 2013): plain V is inflated on small samples."""
    n = table.sum()
    r, k = table.shape
    if n <= 1 or min(r, k) < 2:
        return None
    phi2 = chi2 / n
    phi2_corr = max(0.0, phi2 - (k - 1) * (r - 1) / (n - 1))
    r_corr = r - (r - 1) ** 2 / (n - 1)
    k_corr = k - (k - 1) ** 2 / (n - 1)
    denom = min(k_corr - 1, r_corr - 1)
    return math.sqrt(phi2_corr / denom) if denom > 0 else None


def _categorical_columns(frame: pd.DataFrame, kinds: dict[str, str]) -> list[str]:
    cols = [
        c
        for c in frame.columns
        if kinds.get(c) in ("categorical", "boolean") and 2 <= frame[c].dropna().nunique() <= MAX_LEVELS
    ]
    return cols[:MAX_CATEGORICAL]


def _categorical_pairs(frame: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    rows = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            pair = frame[[a, b]].dropna()
            if len(pair) < MIN_N:
                continue
            table = pd.crosstab(pair[a], pair[b]).to_numpy()
            if min(table.shape) < 2:
                continue
            chi = _try(stats.chi2_contingency, table, correction=table.shape == (2, 2))
            if chi is None:
                continue
            v = _cramers_v(table, float(chi.statistic))
            n = int(table.sum())
            rows.append(
                {
                    "a": a,
                    "b": b,
                    "n": n,
                    "chi2": _num(chi.statistic),
                    "dof": int(chi.dof),
                    "p": _p(chi.pvalue),
                    "cramers_v": _num(v),
                    "contingency_c": _num(math.sqrt(chi.statistic / (chi.statistic + n))),
                    # The chi-square approximation needs expected counts of about 5 or more.
                    "low_expected_pct": _num(100.0 * float((chi.expected_freq < 5).mean())),
                }
            )
    adjusted = benjamini_hochberg([r["p"] for r in rows])
    for r, p_adj in zip(rows, adjusted, strict=True):
        r["p_adj"] = p_adj
        r["strength"] = _label(r["cramers_v"] or 0, STRENGTHS)
        r["reliable"] = (r["low_expected_pct"] or 0) <= 20
    rows.sort(key=lambda r: -(r["cramers_v"] or 0))
    return rows[:TOP_PAIRS]


def goodman_kruskal_gamma(table: np.ndarray) -> tuple[float | None, float | None]:
    """Gamma = (C - D) / (C + D) from a contingency table with ordered rows and columns.

    Ties are ignored, which makes gamma the right choice for coarse ordinal scales (ratings, grades).
    Returns (gamma, approximate two-sided p-value).
    """
    t = table.astype(float)
    rows, cols = t.shape
    concordant = discordant = 0.0
    for i in range(rows):
        for j in range(cols):
            concordant += t[i, j] * t[i + 1 :, j + 1 :].sum()
            discordant += t[i, j] * t[i + 1 :, :j].sum()
    if concordant + discordant == 0:
        return None, None
    gamma = (concordant - discordant) / (concordant + discordant)
    n = t.sum()
    if abs(gamma) >= 1:
        return gamma, 0.0
    z = gamma * math.sqrt((concordant + discordant) / (n * (1 - gamma**2)))
    return gamma, float(2 * stats.norm.sf(abs(z)))


def _ordinal_codes(frame: pd.DataFrame, cols: list[str], kinds: dict[str, str]) -> dict[str, pd.Series]:
    """Integer codes for columns that can be treated as ordered scales.

    Low-cardinality numeric columns (ratings, counts) are used as they are; a few continuous
    columns are cut into quintiles so that they can be compared with the ordinal ones.
    """
    codes: dict[str, pd.Series] = {}
    for c in cols:
        s = frame[c].dropna()
        if s.nunique() <= MAX_ORDINAL_LEVELS:
            codes[c] = frame[c].rank(method="dense")
    continuous = [c for c in cols if c not in codes][:6]
    for c in continuous:
        binned = _try(pd.qcut, frame[c], 5, labels=False, duplicates="drop")
        if binned is not None and binned.nunique() >= 3:
            codes[f"{c} (quintiles)"] = binned.astype(float) + 1
    return codes


def _ordinal_pairs(frame: pd.DataFrame, cols: list[str], kinds: dict[str, str]) -> list[dict[str, Any]]:
    codes = _ordinal_codes(frame, cols, kinds)
    ordinal = [c for c in codes if not c.endswith("(quintiles)")]
    names = list(codes)
    rows = []
    for a in ordinal:
        for b in names:
            if b == a or (b in ordinal and names.index(b) < names.index(a)):
                continue
            pair = pd.concat([codes[a], codes[b]], axis=1, keys=["a", "b"]).dropna()
            if len(pair) < MIN_N or pair["a"].nunique() < 2 or pair["b"].nunique() < 2:
                continue
            table = pd.crosstab(pair["a"], pair["b"]).to_numpy()
            gamma, gamma_p = goodman_kruskal_gamma(table)
            tau = _try(stats.kendalltau, pair["a"], pair["b"], variant="b")
            d_ab = _try(stats.somersd, pair["a"].to_numpy(), pair["b"].to_numpy())
            d_ba = _try(stats.somersd, pair["b"].to_numpy(), pair["a"].to_numpy())
            if gamma is None:
                continue
            rows.append(
                {
                    "a": a,
                    "b": b,
                    "n": len(pair),
                    "gamma": _num(gamma),
                    "gamma_p": _p(gamma_p),
                    "kendall_tau_b": _num(tau.statistic) if tau else None,
                    # Somers' d is asymmetric: D(Y|X) treats Y as the dependent column.
                    "somers_d_b_on_a": _num(d_ab.statistic) if d_ab else None,
                    "somers_d_a_on_b": _num(d_ba.statistic) if d_ba else None,
                    "p": _p(d_ab.pvalue) if d_ab else _p(gamma_p),
                }
            )
    adjusted = benjamini_hochberg([r["p"] for r in rows])
    for r, p_adj in zip(rows, adjusted, strict=True):
        r["p_adj"] = p_adj
        r["strength"] = _label(r["gamma"] or 0, STRENGTHS)
    rows.sort(key=lambda r: -abs(r["gamma"] or 0))
    return rows[:TOP_PAIRS]


def _group_effects(frame: pd.DataFrame, numeric: list[str], cats: list[str]) -> list[dict[str, Any]]:
    rows = []
    for g in cats:
        levels = frame[g].value_counts()
        levels = levels[levels >= MIN_GROUP]
        if not 2 <= len(levels) <= MAX_GROUP_LEVELS:
            continue
        for c in numeric[:10]:
            sub = frame[[c, g]].dropna()
            sub = sub[sub[g].isin(levels.index)]
            groups = [sub.loc[sub[g] == lvl, c].to_numpy(dtype=float) for lvl in levels.index]
            if any(len(x) < MIN_GROUP for x in groups) or sub[c].nunique() < 2:
                continue
            anova = _try(stats.f_oneway, *groups)
            kruskal = _try(stats.kruskal, *groups)
            levene = _try(stats.levene, *groups, center="median")  # Brown-Forsythe: robust to non-normality
            if anova is None:
                continue
            grand = sub[c].mean()
            ssb = sum(len(x) * (x.mean() - grand) ** 2 for x in groups)
            sst = float(((sub[c] - grand) ** 2).sum())
            eta2 = ssb / sst if sst else 0.0
            row = {
                "numeric": c,
                "group": g,
                "groups": len(groups),
                "n": int(len(sub)),
                "f": _num(anova.statistic),
                "p": _p(anova.pvalue),
                "eta_squared": _num(eta2),
                "effect": _label(eta2, EFFECT_ETA),
                "kruskal_h": _num(kruskal.statistic) if kruskal else None,
                "p_kruskal": _p(kruskal.pvalue) if kruskal else None,
                "levene_w": _num(levene.statistic) if levene else None,
                "p_levene": _p(levene.pvalue) if levene else None,
                "means": {str(lvl): _num(x.mean()) for lvl, x in zip(levels.index, groups, strict=True)},
            }
            if len(groups) == 2:
                row.update(_two_groups(groups[0], groups[1]))
            rows.append(row)
    adjusted = benjamini_hochberg([r["p"] for r in rows])
    for r, p_adj in zip(rows, adjusted, strict=True):
        r["p_adj"] = p_adj
    rows.sort(key=lambda r: -(r["eta_squared"] or 0))
    return rows[:TOP_PAIRS]


def _two_groups(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    """Welch t-test, Mann-Whitney U and three effect sizes for exactly two groups."""
    welch = _try(stats.ttest_ind, x, y, equal_var=False)
    mw = _try(stats.mannwhitneyu, x, y, alternative="two-sided")
    n1, n2 = len(x), len(y)
    pooled = math.sqrt(((n1 - 1) * x.var(ddof=1) + (n2 - 1) * y.var(ddof=1)) / (n1 + n2 - 2))
    d = (x.mean() - y.mean()) / pooled if pooled else None
    hedges = d * (1 - 3 / (4 * (n1 + n2) - 9)) if d is not None else None  # small-sample correction
    cliff = (2 * mw.statistic / (n1 * n2) - 1) if mw else None  # P(x > y) - P(x < y)
    return {
        "welch_t": _num(welch.statistic) if welch else None,
        "p_welch": _p(welch.pvalue) if welch else None,
        "mann_whitney_u": _num(mw.statistic) if mw else None,
        "p_mann_whitney": _p(mw.pvalue) if mw else None,
        "cohens_d": _num(d),
        "hedges_g": _num(hedges),
        "cliffs_delta": _num(cliff),
        "cliffs_effect": _label(cliff, EFFECT_CLIFF) if cliff is not None else None,
        "d_effect": _label(d, EFFECT_D) if d is not None else None,
    }
