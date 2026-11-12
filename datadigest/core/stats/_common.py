"""Limits, labels and small helpers shared by the statistics modules."""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np

SEED = 7
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
