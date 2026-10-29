"""The advanced statistics, checked against values worked out independently."""

import json

import numpy as np
import pandas as pd
import pytest

from datadigest.core import stats
from datadigest.core.loader import load_csv
from datadigest.core.profile import build_profile
from datadigest.core.report import render_report
from tests.conftest import SAMPLES


def _columns(frame: pd.DataFrame, kinds: dict[str, str], **extra) -> list[dict]:
    """Minimal profile column dicts, the part of a profile that build_advanced reads."""
    result = []
    for name in frame.columns:
        missing = int(frame[name].isna().sum())
        unique = int(frame[name].nunique())
        result.append(
            {
                "name": name,
                "kind": kinds[name],
                "dtype": str(frame[name].dtype),
                "missing_pct": 100 * missing / len(frame),
                "unique": unique,
                "unique_pct": 100 * unique / max(1, len(frame) - missing),
                **extra,
            }
        )
    return result


def advanced(frame: pd.DataFrame, kinds: dict[str, str], sampled: bool = False) -> dict:
    return stats.build_advanced(
        frame, frame, kinds, _columns(frame, kinds), total_rows=len(frame), sampled=sampled
    )


@pytest.fixture
def rng():
    return np.random.default_rng(42)


# ------------------------------------------------------------------ building blocks


def test_benjamini_hochberg_matches_the_textbook_example():
    adjusted = stats.benjamini_hochberg([0.01, 0.04, 0.03, 0.005])
    assert adjusted == [0.02, 0.04, 0.04, 0.02]
    assert stats.benjamini_hochberg([None, 0.5]) == [None, 0.5]
    assert stats.benjamini_hochberg([]) == []


def test_gamma_is_concordant_minus_discordant_over_their_sum():
    table = np.array([[10, 2], [3, 15]])
    gamma, p = stats.goodman_kruskal_gamma(table)
    assert gamma == pytest.approx((150 - 6) / (150 + 6))
    assert p < 0.001
    perfect, _ = stats.goodman_kruskal_gamma(np.array([[5, 0], [0, 5]]))
    assert perfect == 1.0
    reversed_, _ = stats.goodman_kruskal_gamma(np.array([[0, 5], [5, 0]]))
    assert reversed_ == -1.0
    assert stats.goodman_kruskal_gamma(np.array([[4, 4]])) == (None, None)  # one row: nothing to rank


def test_cramers_v_is_one_for_a_perfect_link_and_near_zero_for_none():
    from scipy.stats import chi2_contingency

    linked = np.array([[50, 0], [0, 50]])
    assert stats._cramers_v(linked, chi2_contingency(linked, correction=False)[0]) == pytest.approx(
        1, abs=0.02
    )
    independent = np.array([[25, 25], [25, 25]])
    assert stats._cramers_v(independent, chi2_contingency(independent, correction=False)[0]) == 0


def test_two_group_effect_sizes():
    x = np.arange(1, 11, dtype=float)
    y = np.arange(6, 16, dtype=float)
    out = stats._two_groups(x, y)
    # Cohen's d: (5.5 - 10.5) / pooled std (3.0277)
    assert out["cohens_d"] == pytest.approx(
        -5 / np.sqrt(((9 * x.var(ddof=1)) + (9 * y.var(ddof=1))) / 18), abs=1e-5
    )
    # Cliff's delta, by brute force: P(x > y) - P(x < y)
    greater = sum(a > b for a in x for b in y)
    smaller = sum(a < b for a in x for b in y)
    assert out["cliffs_delta"] == pytest.approx((greater - smaller) / (len(x) * len(y)))
    assert out["cliffs_effect"] == "large" and out["d_effect"] == "large"
    assert out["hedges_g"] == pytest.approx(out["cohens_d"] * (1 - 3 / (4 * 20 - 9)), abs=1e-5)
    assert out["p_welch"] < 0.05 and out["p_mann_whitney"] < 0.05


# ------------------------------------------------------------------ distributions


def test_moments_match_numpy(rng):
    x = rng.normal(50, 10, 400)
    d = stats._distribution("x", pd.Series(x))
    assert d["variance"] == pytest.approx(np.var(x, ddof=1), rel=1e-5)
    assert d["std"] == pytest.approx(np.std(x, ddof=1), rel=1e-5)
    assert d["cv"] == pytest.approx(np.std(x, ddof=1) / np.mean(x), rel=1e-4)
    assert d["median"] == pytest.approx(np.median(x), rel=1e-5)
    assert d["mad"] == pytest.approx(np.median(np.abs(x - np.median(x))), rel=1e-5)
    lo, hi = d["ci95_mean"]
    assert lo < x.mean() < hi
    assert hi - lo == pytest.approx(2 * 1.966 * x.std(ddof=1) / np.sqrt(400), rel=0.01)


@pytest.mark.parametrize(
    ("make", "best", "shape"),
    [
        (lambda r: r.normal(0, 1, 800), {"norm"}, {"approximately normal"}),
        (lambda r: r.lognormal(0, 0.9, 800), {"lognorm", "gamma", "weibull_min"}, {"right-skewed"}),
        (lambda r: r.exponential(3.0, 800), {"expon", "gamma", "weibull_min"}, {"right-skewed"}),
        (lambda r: r.uniform(10, 20, 800), {"uniform"}, {"not normal", "flat (light-tailed)"}),
    ],
)
def test_distribution_detection(rng, make, best, shape):
    d = stats._distribution("x", pd.Series(make(rng)))
    assert d["best_fit"] in best, d["fits"]
    assert d["shape"] in shape
    assert d["fits"] == sorted(d["fits"], key=lambda f: f["ks_stat"])
    if shape == {"approximately normal"}:
        assert d["normality"]["rejected"] is False


def test_normal_data_is_not_rejected_but_skewed_data_is(rng):
    assert stats._normality(rng.normal(size=500))["rejected"] is False
    assert stats._normality(rng.exponential(size=500))["rejected"] is True


def test_discrete_and_constant_columns_get_no_distribution_fit():
    ratings = stats._distribution("r", pd.Series([1, 2, 3, 4, 5] * 20, dtype=float))
    assert ratings["fits"] == [] and ratings["shape"] == "discrete"
    flat = stats._distribution("c", pd.Series([7.0] * 30))
    assert flat["fits"] == [] and flat["normality"] is None
    assert stats._distribution("tiny", pd.Series([1.0, 2.0])) is None


# ------------------------------------------------------------------ associations


def test_numeric_pairs_find_the_planted_relationship(rng):
    a = rng.normal(size=300)
    frame = pd.DataFrame({"a": a, "b": 2 * a + rng.normal(scale=0.3, size=300), "c": rng.normal(size=300)})
    pairs = stats._numeric_pairs(frame, ["a", "b", "c"])
    top = pairs[0]
    assert (top["a"], top["b"]) == ("a", "b")
    assert top["pearson"] > 0.9 and top["strength"] == "very strong" and top["p_adj"] < 0.001
    assert top["kendall"] > 0.7
    unrelated = next(p for p in pairs if "c" in (p["a"], p["b"]))
    assert unrelated["p_adj"] > 0.05 or abs(unrelated["pearson"]) < 0.2


def test_categorical_pairs_detect_dependence_and_independence(rng):
    group = rng.choice(["x", "y"], 400)
    linked = np.where(rng.random(400) < 0.9, group, rng.choice(["x", "y"], 400))
    frame = pd.DataFrame({"g": group, "linked": linked, "noise": rng.choice(["p", "q", "r"], 400)})
    kinds = dict.fromkeys(frame, "categorical")
    pairs = stats._categorical_pairs(frame, stats._categorical_columns(frame, kinds))
    by = {(p["a"], p["b"]): p for p in pairs}
    assert by[("g", "linked")]["cramers_v"] > 0.6 and by[("g", "linked")]["p_adj"] < 0.001
    assert by[("g", "noise")]["cramers_v"] < 0.15
    assert all(p["reliable"] for p in pairs)


def test_group_effects_report_eta_squared_and_two_group_extras(rng):
    group = np.repeat(["low", "high"], 150)
    value = np.concatenate([rng.normal(10, 2, 150), rng.normal(14, 2, 150)])
    frame = pd.DataFrame({"v": value, "g": group, "flat": rng.normal(size=300)})
    rows = stats._group_effects(frame, ["v", "flat"], ["g"])
    strong = rows[0]
    assert strong["numeric"] == "v" and strong["effect"] == "large" and strong["eta_squared"] > 0.3
    assert strong["p_adj"] < 0.001 and strong["p_levene"] > 0.01
    assert (
        strong["cohens_d"] < -1 and strong["cliffs_delta"] < -0.5
    )  # 'high' sorts first by count, ties by order
    assert rows[1]["effect"] in ("negligible", "small")


def test_ordinal_pairs_use_gamma_and_somers_d(rng):
    x = rng.integers(1, 6, 400).astype(float)
    y = np.clip(x + rng.integers(-1, 2, 400), 1, 5)
    frame = pd.DataFrame({"x": x, "y": y, "amount": rng.normal(size=400)})
    pairs = stats._ordinal_pairs(frame, ["x", "y", "amount"], dict.fromkeys(frame, "numeric"))
    top = pairs[0]
    assert (top["a"], top["b"]) == ("x", "y")
    assert top["gamma"] > 0.8 and top["somers_d_b_on_a"] > 0.5 and top["somers_d_a_on_b"] > 0.5
    assert top["kendall_tau_b"] > 0.5 and top["p_adj"] < 0.001
    assert any(p["b"] == "amount (quintiles)" for p in pairs)  # continuous columns are cut into quintiles


# ------------------------------------------------------------------ consistency


def test_label_variants_and_format_consistency():
    cities = pd.Series(["Istanbul", "istanbul ", "Ankara", "Ankara", "ISTANBUL", "Izmir"] * 5)
    variants = stats._label_variants(cities)
    assert variants["groups"] == 1 and "'Istanbul'" in variants["examples"][0]
    ids = pd.Series(["AB-123"] * 18 + ["ab-12", "999"])
    fmt = stats._format_consistency(ids)
    assert fmt["share"] == 0.9 and fmt["dominant"] == "AA-999" and fmt["patterns"] == 3


def test_cronbach_alpha_is_high_for_one_construct_and_low_for_noise(rng):
    latent = rng.normal(size=400)
    items = pd.DataFrame({f"q{i}": latent + rng.normal(scale=0.6, size=400) for i in range(5)})
    good = stats.cronbach_alpha(items)
    assert good["alpha"] > 0.85 and good["label"] in ("good", "excellent")
    assert all(i["item_total_r"] > 0.6 for i in good["item_stats"])
    noise = stats.cronbach_alpha(pd.DataFrame(rng.normal(size=(400, 5)), columns=list("abcde")))
    assert noise["alpha"] < 0.3 and noise["label"] == "unacceptable"
    assert stats.cronbach_alpha(items.iloc[:, :2]) is None  # needs at least three items
    assert stats.cronbach_alpha(items.iloc[:20]) is None  # and enough complete rows


def test_conflicting_duplicate_keys_are_found():
    ids = list(range(1, 41))
    cities = [f"city{i}" for i in ids]
    ids[5] = ids[4]  # the same id with a different city: a real conflict
    ids[11] = ids[10]
    cities[11] = cities[10]  # the same id and the same city: a harmless repeat
    frame = pd.DataFrame({"id": ids, "city": cities})
    columns = [
        {"name": "id", "dtype": "int64", "unique_pct": 95.0},
        {"name": "city", "dtype": "str", "unique_pct": 95.0},
    ]
    found = stats._key_conflicts(frame, {"id": "numeric", "city": "categorical"}, columns)
    assert found == {"key": "id", "repeated_keys": 2, "conflicting_keys": 1}


def test_consistency_of_the_sample_file():
    profile = build_profile(load_csv((SAMPLES / "sales.csv").read_bytes()))
    consistency = profile["advanced"]["consistency"]
    by = {c["name"]: c for c in consistency["columns"]}
    assert by["order_id"]["completeness"] == 1.0
    assert by["rating"]["completeness"] == pytest.approx(0.9045, abs=0.001)
    assert 0 < consistency["score"] <= 100 and consistency["grade"] in "ABCD"
    assert consistency["key_conflicts"]["key"] == "order_id"
    assert (
        consistency["key_conflicts"]["repeated_keys"] == 5
        and consistency["key_conflicts"]["conflicting_keys"] == 0
    )


# ------------------------------------------------------------------ sensitivity


def test_one_extreme_value_makes_the_mean_sensitive_but_not_the_median(rng):
    x = np.append(rng.normal(100, 5, 99), 5_000.0)
    frame = pd.DataFrame({"x": x})
    out = stats._sensitivity(frame, ["x"], [])["columns"][0]
    assert out["outliers_removed"] >= 1
    assert out["robustness"] == "sensitive" and out["mean_shift_pct"] < -25
    assert abs(out["median_shift_pct"]) < 2
    lo, hi = out["bootstrap_median_ci"]
    assert 95 < lo < hi < 105  # the median ignores the outlier, the mean's interval does not
    assert out["trimmed_mean"] == pytest.approx(100, abs=3)


def test_an_outlier_can_manufacture_a_correlation(rng):
    a = np.append(rng.normal(size=60), 40.0)
    b = np.append(rng.normal(size=60), 40.0)
    frame = pd.DataFrame({"a": a, "b": b})
    pairs = stats._numeric_pairs(frame, ["a", "b"])
    sens = stats._sensitivity(frame, ["a", "b"], pairs)["correlations"][0]
    assert sens["pearson"] > 0.9 and abs(sens["pearson_without_outliers"]) < 0.4
    assert sens["fragile"] is True and sens["rows_dropped"] >= 1


# ------------------------------------------------------------------ whole profile


def test_sampling_is_capped_and_reproducible():
    big = pd.DataFrame({"x": np.arange(stats.MAX_ROWS + 5_000, dtype=float)})
    sample, sampled = stats.sample_frame(big, len(big))
    again, _ = stats.sample_frame(big, len(big))
    assert sampled and len(sample) == stats.MAX_ROWS and sample.equals(again)
    small, flag = stats.sample_frame(big.iloc[:100], 100)
    assert not flag and len(small) == 100


def test_the_profile_carries_every_section_and_is_strict_json():
    profile = build_profile(load_csv((SAMPLES / "sales.csv").read_bytes()))
    adv = profile["advanced"]
    json.dumps(profile, allow_nan=False)  # no NaN or Infinity anywhere
    assert set(adv) == {"sample", "distributions", "associations", "consistency", "sensitivity", "notes"}
    assert set(adv["associations"]) == {"numeric", "categorical", "ordinal", "by_group"}
    assert adv["sample"] == {"rows": 1005, "of": 1005, "sampled": False}
    names = {d["name"] for d in adv["distributions"]}
    assert {"units", "unit_price", "revenue"} <= names
    pair_columns = {c for p in adv["associations"]["numeric"] for c in (p["a"], p["b"])}
    assert "order_id" not in pair_columns  # an identifier says nothing about anything
    assert adv["sensitivity"]["columns"] and adv["sensitivity"]["correlations"]


def test_awkward_files_do_not_break_the_statistics():
    tiny = build_profile(load_csv(b"a,b\n1,x\n2,y\n3,x\n"))["advanced"]
    assert tiny["distributions"] == [] and tiny["associations"]["numeric"] == []
    text_only = build_profile(load_csv(b"w\n" + b"hello world\nfoo bar\n" * 20))["advanced"]
    assert text_only["distributions"] == []
    constant = build_profile(load_csv(b"a,b\n" + b"5,1\n5,2\n5,3\n" * 10))["advanced"]
    assert [d["name"] for d in constant["distributions"]] == ["b"]  # a has no variation


def test_the_report_and_api_expose_the_statistics(client):
    from tests.conftest import upload

    dataset = upload(client).json()
    profile = client.get(f"/api/datasets/{dataset['id']}/profile").json()
    assert profile["advanced"]["distributions"]
    html = client.get(f"/api/datasets/{dataset['id']}/report").text
    assert "<h2>Statistics</h2>" in html and "Cramér" in html and "Sensitivity to outliers" in html
    profile = build_profile(load_csv((SAMPLES / "sales.csv").read_bytes()))
    assert "Consistency: grade" in render_report(profile, "sales")
