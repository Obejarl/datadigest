"""The offline command-line tool: python -m datadigest.cli report|profile FILE."""

import json

from datadigest.cli import main
from tests.conftest import SAMPLES


def test_report_writes_a_self_contained_html_file(tmp_path, capsys):
    out = tmp_path / "sales.html"
    assert main(["report", str(SAMPLES / "sales.csv"), "-o", str(out), "--title", "Sales"]) == 0
    html = out.read_text(encoding="utf-8")
    assert "<title>Sales" in html and "unit_price" in html
    assert "1005 rows" in capsys.readouterr().out


def test_report_default_output_sits_next_to_the_input(tmp_path):
    src = tmp_path / "data.csv"
    src.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    assert main(["report", str(src)]) == 0
    assert (tmp_path / "data.report.html").exists()


def test_profile_prints_json_with_the_quality_score(capsys):
    assert main(["profile", str(SAMPLES / "tr_survey.csv")]) == 0
    profile = json.loads(capsys.readouterr().out)
    assert profile["summary"]["rows"] == 300
    assert profile["summary"]["quality"]["grade"] in "ABCD"
    assert "şehir" in [c["name"] for c in profile["columns"]]  # non-ASCII survives


def test_errors_are_reported_without_a_traceback(tmp_path, capsys):
    assert main(["profile", str(tmp_path / "missing.csv")]) == 1
    empty = tmp_path / "empty.csv"
    empty.write_text("only_header\n", encoding="utf-8")
    assert main(["report", str(empty)]) == 1
    assert capsys.readouterr().err.count("error:") == 2


def test_one_command_start_migrates_then_serves(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect

    import datadigest.__main__ as start
    from datadigest.config import get_settings

    url = f"sqlite:///{(tmp_path / 'start.db').as_posix()}"
    monkeypatch.setattr(get_settings(), "database_url", url)
    served = {}
    assert start.main(["--port", "9123"], serve=lambda app, **kw: served.update(app=app, **kw)) == 0
    assert served == {"app": "datadigest.api.main:app", "host": "127.0.0.1", "port": 9123}
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"datasets", "dataset_files", "users", "optimizations"} <= tables
