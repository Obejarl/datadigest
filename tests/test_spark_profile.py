"""The Spark engine must agree with the pandas engine.

These tests start a local Spark session (needs pyspark and a Java runtime), so they are skipped
where those are missing; CI runs them in the `spark` job.
"""

import math
import os
from pathlib import Path

import pandas as pd
import pytest

from datadigest.config import Settings
from datadigest.core import spark_profile
from datadigest.core.loader import LoadError, load_csv
from datadigest.core.profile import build_profile

pytest.importorskip("pyspark")
if not spark_profile.spark_available():
    pytest.skip("no Java runtime found", allow_module_level=True)

pytestmark = pytest.mark.spark

SAMPLES = Path(__file__).parent.parent / "samples"

MESSY = """id,Name,name,joined,score,active,group,note,empty,flat
1,Ann,x,2024-01-05,10.5,yes,a,"likes, commas",,7
2,Bob,y,2024-01-06,11.5,no,a,plain note,,7
3,Cy,z,2024-02-07,NA,yes,b,another one,,7
3,Cy,z,2024-02-07,NA,yes,b,another one,,7
4,Di,w,2024-03-09,13.0,no,b,final note here,,7
5,Ed,v,2024-04-10,9.0,yes,a,more words in note,,7
6,Flo,u,2024-05-11,100.0,no,c,last but one,,7
7,Gus,t,2024-06-12,10.0,yes,c,the end,,7
8,Hal,s,2024-07-13,10.1,no,c,not a date row,,7
9,Ivy,r,2024-08-14,10.2,yes,a,ok,,7
10,Jo,q,2024-09-15,10.3,no,a,ok again,,7
"""


@pytest.fixture(scope="module")
def settings():
    return Settings(spark_driver_memory="1g", spark_shuffle_partitions=2)


def _same(pandas_value, spark_value, where=""):
    """Walk both profiles; numbers must match to 6 digits, everything else exactly."""
    if isinstance(pandas_value, dict):
        assert pandas_value.keys() == spark_value.keys(), where
        for key in pandas_value:
            _same(pandas_value[key], spark_value[key], f"{where}/{key}")
    elif isinstance(pandas_value, list):
        assert len(pandas_value) == len(spark_value), where
        for i, (a, b) in enumerate(zip(pandas_value, spark_value, strict=True)):
            _same(a, b, f"{where}[{i}]")
    elif isinstance(pandas_value, float) and not isinstance(pandas_value, bool):
        assert spark_value == pytest.approx(pandas_value, rel=1e-6, abs=1e-9), where
    else:
        assert pandas_value == spark_value, where


def _comparable(profile: dict) -> dict:
    """Drop what is allowed to differ: engine name, size on disk, raw preview, order of tied top values."""
    profile = {**profile, "summary": dict(profile["summary"])}
    for key in ("engine", "memory_bytes"):
        profile["summary"].pop(key)
    profile.pop("preview")
    profile["columns"] = [
        {**c, "top": sorted(c["top"], key=lambda t: (-t["count"], t["value"]))} if "top" in c else c
        for c in profile["columns"]
    ]
    return profile


def _both(path: Path, settings):
    pandas_profile = build_profile(load_csv(path.read_bytes()))
    spark_profile_ = spark_profile.build_profile_spark(path, settings)
    return pandas_profile, spark_profile_


@pytest.mark.parametrize("sample", ["sales.csv", "tr_survey.csv"])
def test_matches_pandas_on_the_bundled_samples(sample, settings):
    pandas_profile, spark_result = _both(SAMPLES / sample, settings)
    assert spark_result["summary"]["engine"] == "spark"
    assert pandas_profile["summary"]["engine"] == "pandas"
    _same(_comparable(pandas_profile), _comparable(spark_result))


def test_matches_pandas_on_a_messy_file(tmp_path, settings):
    path = tmp_path / "messy.csv"
    path.write_text(MESSY, encoding="utf-8")
    pandas_profile, spark_result = _both(path, settings)
    _same(_comparable(pandas_profile), _comparable(spark_result))

    summary = spark_result["summary"]
    assert summary["duplicate_rows"] == 1
    names = [c["name"] for c in spark_result["columns"]]
    assert names[1:3] == ["Name", "name"]  # case differs, so not a duplicate header
    kinds = {c["name"]: c["kind"] for c in spark_result["columns"]}
    assert kinds["joined"] == "datetime"
    assert kinds["active"] == "boolean"
    assert kinds["score"] == "numeric"
    assert kinds["empty"] == "numeric"  # an all-empty column is a float column of NaN in pandas too


def test_duplicate_header_names_are_numbered_like_pandas(tmp_path, settings):
    path = tmp_path / "dups.csv"
    path.write_text("a,a,b\n1,2,3\n4,5,6\n", encoding="utf-8")
    pandas_profile, spark_result = _both(path, settings)
    assert [c["name"] for c in spark_result["columns"]] == [c["name"] for c in pandas_profile["columns"]]
    assert [c["name"] for c in spark_result["columns"]] == ["a", "a.1", "b"]


def test_byte_order_mark_does_not_end_up_in_the_first_column_name(tmp_path, settings):
    path = tmp_path / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbfcity,n\nIstanbul,1\nAnkara,2\n")
    result = spark_profile.build_profile_spark(path, settings)
    assert result["summary"]["encoding"] == "utf-8-sig"
    assert [c["name"] for c in result["columns"]] == ["city", "n"]


def test_turkish_windows_encoding_is_decoded(tmp_path, settings):
    path = tmp_path / "tr.csv"
    path.write_bytes("şehir;fiyat\nİstanbul;1.234,5\nIğdır;2,5\nÇorum;3,0\n".encode("cp1254"))
    result = spark_profile.build_profile_spark(path, settings)
    assert result["summary"]["encoding"] == "cp1254"
    assert result["columns"][0]["name"] == "şehir"
    assert {t["value"] for t in result["columns"][0]["top"]} == {"İstanbul", "Iğdır", "Çorum"}
    assert result["columns"][1]["kind"] == "numeric"  # decimal comma
    assert result["columns"][1]["max"] == 1234.5


FRAME = pd.DataFrame({"id": [1, 2, 3], "tag": ["a", "b", "a"], "x": [1.5, None, 2.5], "part": [1, 1, 2]})


def _check_parquet_profile(result):
    assert result["summary"]["rows"] == 3
    assert result["summary"]["encoding"] == "parquet"
    assert result["summary"]["memory_bytes"] > 0
    by_name = {c["name"]: c for c in result["columns"]}
    assert by_name["id"]["dtype"] == "int64"
    assert by_name["x"]["missing"] == 1
    assert by_name["tag"]["top"][0] == {"value": "a", "count": 2}


def test_parquet_files_are_profiled(tmp_path, settings):
    FRAME.to_parquet(tmp_path / "data.parquet")
    _check_parquet_profile(spark_profile.build_profile_spark(tmp_path / "data.parquet", settings))


@pytest.mark.skipif(os.name == "nt", reason="listing a folder needs Hadoop's winutils.exe on Windows")
def test_a_partitioned_parquet_folder_is_profiled(tmp_path, settings):
    FRAME.to_parquet(tmp_path / "dataset.parquet", partition_cols=["part"])
    _check_parquet_profile(spark_profile.build_profile_spark(tmp_path / "dataset.parquet", settings))


def test_approximate_quantiles_take_over_on_huge_inputs(monkeypatch, tmp_path, settings):
    path = tmp_path / "n.csv"
    path.write_text("v\n" + "\n".join(str(i) for i in range(1, 1001)) + "\n", encoding="utf-8")
    monkeypatch.setattr(spark_profile, "EXACT_QUANTILE_ROWS", 10)
    approx = spark_profile.build_profile_spark(path, settings)["columns"][0]
    exact = build_profile(load_csv(path.read_bytes()))["columns"][0]
    assert approx["median"] == pytest.approx(exact["median"], rel=0.01)
    assert approx["p25"] == pytest.approx(exact["p25"], rel=0.01)
    assert approx["mean"] == exact["mean"]  # only the quantiles are approximate


def test_missing_values_never_land_in_the_histogram(tmp_path, settings):
    path = tmp_path / "gaps.csv"
    path.write_text("x,y\n1,a\n2,a\n,a\nNA,a\n3,a\n4,a\n", encoding="utf-8")
    column = spark_profile.build_profile_spark(path, settings)["columns"][0]
    assert column["missing"] == 2
    assert sum(column["histogram"]["counts"]) == 4


def test_a_constant_column_gets_a_histogram_and_a_warning(tmp_path, settings):
    path = tmp_path / "flat.csv"
    path.write_text("x,y\n5,1\n5,2\n5,3\n", encoding="utf-8")
    result = spark_profile.build_profile_spark(path, settings)
    assert sum(result["columns"][0]["histogram"]["counts"]) == 3
    assert any(w["type"] == "constant" for w in result["warnings"])


def test_a_file_with_only_a_header_is_rejected(tmp_path, settings):
    path = tmp_path / "header.csv"
    path.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(LoadError, match="no data rows"):
        spark_profile.build_profile_spark(path, settings)


def test_an_empty_file_is_rejected(tmp_path, settings):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(LoadError, match="empty"):
        spark_profile.build_profile_spark(path, settings)


def test_spark_failures_become_friendly_load_errors(monkeypatch, settings):
    monkeypatch.setattr(spark_profile, "spark_available", lambda: False)
    with pytest.raises(LoadError, match="needs pyspark"):
        spark_profile.get_session(settings)


def test_a_non_ascii_install_path_on_windows_gets_an_explanation(monkeypatch):
    monkeypatch.setattr(spark_profile.os, "name", "nt")
    monkeypatch.setenv("SPARK_HOME", "ignored")  # restored afterwards; the setting below replaces it
    with pytest.raises(LoadError, match="non-ASCII"):
        spark_profile.get_session(Settings(spark_home="C:/Users/Çağrı/pyspark"))


def test_the_profile_feeds_the_existing_report_and_charts(tmp_path, settings):
    from datadigest.core.charts import build_charts
    from datadigest.core.report import render_report

    result = spark_profile.build_profile_spark(SAMPLES / "sales.csv", settings)
    assert build_charts(result)
    assert "sales.csv" in render_report(result, "sales.csv")
    assert not math.isnan(result["summary"]["quality"]["score"])


def test_the_spark_home_setting_is_exported_for_the_launcher(monkeypatch, settings):
    import pyspark

    home = os.environ.get("SPARK_HOME") or str(Path(pyspark.__file__).parent)
    monkeypatch.setenv("SPARK_HOME", "ignored")
    spark_profile.get_session(Settings(spark_home=home, spark_driver_memory="1g", spark_shuffle_partitions=2))
    assert os.environ["SPARK_HOME"] == home
