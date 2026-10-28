"""Choosing between the pandas and the Spark engine (no Spark needed to run these)."""

import pytest

from datadigest.config import Settings
from datadigest.core import engines
from datadigest.core.loader import LoadError


@pytest.fixture
def csv(tmp_path):
    path = tmp_path / "data.csv"
    path.write_bytes(b"a,b\n1,x\n2,y\n")
    return path


def test_small_files_stay_on_pandas(csv, monkeypatch):
    monkeypatch.setattr(engines, "spark_available", lambda: True)
    assert engines.choose_engine(csv, "auto", Settings(spark_min_mb=100)) == "pandas"


def test_files_over_the_threshold_go_to_spark_when_it_is_installed(csv, monkeypatch):
    settings = Settings(spark_min_mb=0)
    monkeypatch.setattr(engines, "spark_available", lambda: True)
    assert engines.choose_engine(csv, "auto", settings) == "spark"
    monkeypatch.setattr(engines, "spark_available", lambda: False)
    assert engines.choose_engine(csv, "auto", settings) == "pandas"  # no Spark: degrade, do not fail


def test_parquet_always_needs_spark(tmp_path):
    path = tmp_path / "facts.parquet"
    path.write_bytes(b"PAR1")
    assert engines.choose_engine(path, "auto", Settings()) == "spark"
    with pytest.raises(LoadError, match="Spark engine"):
        engines.profile_path(path, "pandas", Settings())


def test_an_explicit_engine_wins(csv):
    assert engines.choose_engine(csv, "spark", Settings()) == "spark"
    assert engines.choose_engine(csv, "pandas", Settings(spark_min_mb=0)) == "pandas"


def test_unknown_engines_are_rejected(csv):
    with pytest.raises(ValueError, match="engine must be one of"):
        engines.choose_engine(csv, "hadoop", Settings())


def test_profile_path_runs_pandas_and_labels_the_result(csv):
    profile = engines.profile_path(csv, "pandas", Settings())
    assert profile["summary"]["engine"] == "pandas"
    assert profile["summary"]["rows"] == 2


def test_profile_path_hands_big_files_to_spark(csv, monkeypatch):
    calls = []

    def fake(path, settings):
        calls.append(path)
        return {"ok": 1}

    monkeypatch.setattr(engines, "build_profile_spark", fake)
    assert engines.profile_path(csv, "spark", Settings()) == {"ok": 1}
    assert calls == [csv]


def test_the_cli_engine_flag(csv, capsys):
    from datadigest.cli import main

    assert main(["profile", str(csv), "--engine", "pandas"]) == 0
    assert '"engine": "pandas"' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["profile", str(csv), "--engine", "hadoop"])


def test_blank_optional_paths_mean_off():
    assert Settings(spark_home="  ").spark_home is None
