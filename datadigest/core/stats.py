"""Advanced statistics for a profile: distributions, associations, consistency and sensitivity.

Everything here is pure (no database, no HTTP) and works on one pandas DataFrame of already
converted columns, so the pandas and the Spark engine share it: Spark collects a sample of at
most ``MAX_ROWS`` rows and hands it over.

What is in the result (``build_advanced``):

- ``distributions``: per numeric column the moments (mean, variance, CV, skew, kurtosis), robust
  measures (median, MAD, IQR, trimmed mean), a confidence interval for the mean, three normality
  tests and Kolmogorov-Smirnov fits against common distributions;
- ``associations``: Pearson / Spearman / Kendall for numeric pairs, chi-square with Cramér's V
  for categorical pairs, Goodman-Kruskal gamma and Somers' d for ordinal pairs, and
  ANOVA / Kruskal-Wallis / Levene with eta squared (plus Cohen's d and Cliff's delta for two
  groups) for numeric-by-group;
- ``consistency``: completeness, validity, uniqueness and format consistency per column, label
  variants ("Istanbul" vs "istanbul "), conflicting duplicate keys and Cronbach's alpha;
- ``sensitivity``: how much each statistic moves when outliers are dropped, bootstrap confidence
  intervals, and how much each correlation depends on the outliers.

p-values come with a Benjamini-Hochberg adjustment because dozens of tests are run at once, and
every test is paired with an effect size, because with many rows almost any difference is
"significant".
"""

from __future__ import annotations

import math
import re
import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from datadigest.core.profile import GRADES, _num

MAX_ROWS = 50_000  # rows the tests run on; bigger inputs are sampled
SHAPIRO_MAX = 5_000  # Shapiro-Wilk loses accuracy (and speed) above this
FIT_MAX = 5_000  # rows used to fit and test the candidate distributions
BOOTSTRAPS = 300
BOOTSTRAP_ROWS = 5_000
MIN_N = 8
MAX_NUMERIC = 30
MAX_PAIR_COLUMNS = 20
MAX_CATEGORICAL = 12
MAX_LEVELS = 30
MAX_ORDINAL_LEVELS = 10
MAX_GROUP_LEVELS = 12
MIN_GROUP = 5
TOP_PAIRS = 25
TRIM = 0.10
ALPHA = 0.05
SEED = 7

STRENGTHS = ((0.7, "very strong"), (0.5, "strong"), (0.3, "moderate"), (0.1, "weak"), (0.0, "negligible"))
EFFECT_ETA = ((0.14, "large"), (0.06, "medium"), (0.01, "small"), (0.0, "negligible"))
EFFECT_CLIFF = ((0.474, "large"), (0.33, "medium"), (0.147, "small"), (0.0, "negligible"))
EFFECT_D = ((0.8, "large"), (0.5, "medium"), (0.2, "small"), (0.0, "negligible"))
ALPHA_LABELS = ((0.9, "excellent"), (0.8, "good"), (0.7, "acceptable"), (0.6, "questionable"), (0.5, "poor"))

CANDIDATES = ("norm", "lognorm", "expon", "uniform", "gamma", "weibull_min")
POSITIVE_ONLY = {"lognorm", "gamma", "weibull_min"}


def _label(value: float, scale: tuple[tuple[float, str], ...]) -> str:
    return next(name for threshold, name in scale if abs(value) >= threshold)


def _p(value: Any) -> float | None:
    """A p-value, kept in scientific precision (6 decimals would turn 3e-9 into 0)."""
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else float(f"{value:.4g}")


def _try(fn, *args, **kwargs):
    """Run a statistical test; a test that cannot run on this data (constant input...) gives None."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return fn(*args, **kwargs)
        except (ValueError, FloatingPointError, np.linalg.LinAlgError, ZeroDivisionError, RuntimeError):
            return None


def benjamini_hochberg(p_values: list[float | None]) -> list[float | None]:
    """False-discovery-rate adjusted p-values; None stays None."""
    indexed = [(p, i) for i, p in enumerate(p_values) if p is not None]
    adjusted: list[float | None] = [None] * len(p_values)
    m = len(indexed)
    running = 1.0
    for rank, (p, i) in sorted(enumerate(sorted(indexed), 1), key=lambda t: -t[0]):
        running = min(running, p * m / rank)
        adjusted[i] = _p(running)
    return adjusted


# ------------------------------------------------------------------ distributions


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


# ------------------------------------------------------------------ associations


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


# ------------------------------------------------------------------ consistency


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


# ------------------------------------------------------------------ sensitivity


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


# ------------------------------------------------------------------ entry point


def build_advanced(
    frame: pd.DataFrame,
    raw: pd.DataFrame,
    kinds: dict[str, str],
    columns: list[dict],
    *,
    total_rows: int,
    validity: dict[str, float] | None = None,
    sampled: bool = False,
) -> dict[str, Any]:
    """Compute every section.

    ``frame`` holds the converted columns (floats for numeric ones, strings for categorical),
    ``raw`` the original strings, ``columns`` the profile's column dicts (for missing and unique
    counts that were computed on all rows), ``validity`` the share of non-empty values that
    parsed as the column's type.
    """
    numeric = _numeric_columns(frame, kinds)
    distributions = [d for c in numeric if (d := _distribution(c, frame[c])) is not None]
    # Row numbers and IDs are unique integers: correlating them with anything is noise.
    identifiers = {
        c["name"]
        for c in columns
        if kinds.get(c["name"]) == "numeric" and "int" in c.get("dtype", "") and c.get("unique_pct", 0) >= 95
    }
    numeric = [c for c in numeric if c not in identifiers]
    numeric_pairs = _numeric_pairs(frame, numeric)
    cats = _categorical_columns(frame, kinds)
    notes = [
        "p-values are adjusted for the number of tests (Benjamini-Hochberg, column p_adj).",
        "With many rows almost any difference is significant, so read the effect size next to the p-value.",
        "Distribution fits are ranked by the Kolmogorov-Smirnov distance; their p-values are optimistic "
        "because the parameters were estimated from the same data.",
    ]
    if sampled:
        notes.append(f"Computed on a random sample of {len(frame):,} of {total_rows:,} rows.")
    return {
        "sample": {"rows": int(len(frame)), "of": int(total_rows), "sampled": sampled},
        "distributions": distributions,
        "associations": {
            "numeric": numeric_pairs,
            "categorical": _categorical_pairs(frame, cats),
            "ordinal": _ordinal_pairs(frame, numeric, kinds),
            "by_group": _group_effects(frame, numeric, cats),
        },
        "consistency": _consistency(frame, raw, kinds, columns, validity or {}, sampled, numeric),
        "sensitivity": _sensitivity(frame, numeric, numeric_pairs),
        "notes": notes,
    }


def sample_frame(frame: pd.DataFrame, total_rows: int) -> tuple[pd.DataFrame, bool]:
    """At most MAX_ROWS rows, chosen at random but reproducibly."""
    if len(frame) <= MAX_ROWS:
        return frame, False
    return frame.sample(MAX_ROWS, random_state=SEED).sort_index(), True
