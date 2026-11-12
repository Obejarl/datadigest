"""Advanced statistics for a profile: distributions, associations, consistency and sensitivity.

Everything here is pure (no database, no HTTP) and works on one pandas DataFrame of already
converted columns, so the pandas and the Spark engine share it: Spark collects a sample of at
most ``STATS_MAX_ROWS`` rows (``MAX_ROWS`` by default) and hands it over.

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

from typing import Any

import pandas as pd

from datadigest.core.stats._common import SEED, benjamini_hochberg  # noqa: F401
from datadigest.core.stats.associations import (  # noqa: F401
    _categorical_columns,
    _categorical_pairs,
    _cramers_v,
    _group_effects,
    _numeric_columns,
    _numeric_pairs,
    _ordinal_pairs,
    _two_groups,
    goodman_kruskal_gamma,
)
from datadigest.core.stats.consistency import (  # noqa: F401
    _consistency,
    _format_consistency,
    _key_conflicts,
    _label_variants,
    cronbach_alpha,
)
from datadigest.core.stats.distributions import (
    _distribution,
    _normality,  # noqa: F401
)
from datadigest.core.stats.highlights import build_highlights, tests_run
from datadigest.core.stats.sensitivity import _sensitivity

MAX_ROWS = 50_000  # default number of rows the tests run on (STATS_MAX_ROWS); bigger inputs are sampled


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
    associations = {
        "numeric": numeric_pairs,
        "categorical": _categorical_pairs(frame, cats),
        "ordinal": _ordinal_pairs(frame, numeric, kinds),
        "by_group": _group_effects(frame, numeric, cats),
    }
    consistency = _consistency(frame, raw, kinds, columns, validity or {}, sampled, numeric)
    sensitivity = _sensitivity(frame, numeric, numeric_pairs)
    described = [
        d for d in distributions if d["name"] not in identifiers
    ]  # an id has no shape worth a remark
    return {
        "sample": {"rows": int(len(frame)), "of": int(total_rows), "sampled": sampled},
        # Plain sentences first: what is worth a look and what is easy to misread.
        "highlights": build_highlights(described, associations, consistency, sensitivity),
        "tests_run": tests_run(associations),
        "distributions": distributions,
        "associations": associations,
        "consistency": consistency,
        "sensitivity": sensitivity,
        "notes": notes,
    }


def sample_frame(frame: pd.DataFrame, limit: int | None = None) -> tuple[pd.DataFrame, bool]:
    """At most `limit` rows (MAX_ROWS when not given), chosen at random but reproducibly."""
    limit = limit or MAX_ROWS
    if len(frame) <= limit:
        return frame, False
    return frame.sample(limit, random_state=SEED).sort_index(), True
