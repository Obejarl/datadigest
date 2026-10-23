from pathlib import Path

import pytest

from datadigest.core.charts import build_charts
from datadigest.core.loader import LoadError, detect_delimiter, load_csv
from datadigest.core.profile import build_profile
from datadigest.core.report import render_report

SAMPLES = Path(__file__).parent.parent / "samples"


def profile_of(text: str, encoding: str = "utf-8") -> dict:
    return build_profile(load_csv(text.encode(encoding)))


def column(profile: dict, name: str) -> dict:
    return next(c for c in profile["columns"] if c["name"] == name)


# --- loader ---------------------------------------------------------------


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_detects_delimiter(delimiter):
    text = "\n".join(delimiter.join(row) for row in [["a", "b", "c"], ["1", "2", "3"], ["4", "5", "6"]])
    assert detect_delimiter(text) == delimiter


def test_reads_turkish_excel_export():
    raw = "şehir;gelir;tarih\nİstanbul;1.234,50;15.03.2025\nİzmir;980,25;16.03.2025\n".encode("cp1254")
    table = load_csv(raw)
    assert (table.encoding, table.delimiter) == ("cp1254", ";")
    assert list(table.df.columns) == ["şehir", "gelir", "tarih"]
    assert table.df["gelir"].tolist() == [1234.5, 980.25]


def test_utf8_bom_is_detected():
    assert load_csv("a,b\n1,2\n".encode("utf-8-sig")).encoding == "utf-8-sig"


def test_truncates_to_max_rows():
    table = load_csv(("x\n" + "\n".join(str(i) for i in range(50))).encode(), max_rows=10)
    assert len(table.df) == 10 and table.truncated


@pytest.mark.parametrize("raw", [b"", b"   \n  ", b"only_header\n"])
def test_rejects_empty_files(raw):
    with pytest.raises(LoadError):
        load_csv(raw)


# --- profile --------------------------------------------------------------


def test_infers_column_kinds():
    rows = [
        f"{i},{i * 1.5},{'yes' if i % 2 else 'no'},2025-01-{i % 28 + 1:02d},{'ab'[i % 2]},note {i}"
        for i in range(60)
    ]
    p = profile_of("id,price,active,day,group,comment\n" + "\n".join(rows))
    kinds = {c["name"]: c["kind"] for c in p["columns"]}
    assert kinds == {
        "id": "numeric",
        "price": "numeric",
        "active": "boolean",
        "day": "datetime",
        "group": "categorical",
        "comment": "text",
    }


def test_numeric_stats_and_histogram():
    p = profile_of("v\n" + "\n".join(str(i) for i in range(1, 101)))
    v = column(p, "v")
    assert (v["min"], v["max"], v["median"], v["mean"]) == (1, 100, 50.5, 50.5)
    assert sum(v["histogram"]["counts"]) == 100
    assert len(v["histogram"]["edges"]) == len(v["histogram"]["counts"]) + 1


def test_missing_values_and_json_safety():
    p = profile_of("a,b\n1,\n2,\n3,x\n")
    assert column(p, "b")["missing"] == 2
    assert p["summary"]["missing_cells"] == 2
    import json

    json.dumps(p, allow_nan=False)  # NaN would break JSON responses and JSON columns


def test_warnings():
    rows = [f"{i},{i * 2},const,{'' if i < 30 else i}" for i in range(100)]
    p = profile_of("id,double,c,sparse\n" + "\n".join(rows + [rows[0]]))
    types = {(w["type"], tuple(w["columns"])) for w in p["warnings"]}
    assert ("duplicates", ()) in types
    assert ("constant", ("c",)) in types
    assert ("high_missing", ("sparse",)) in types
    assert ("high_correlation", ("id", "double")) in types


def test_unique_floats_and_free_text_are_not_ids():
    rows = [f"{i},{i * 1.37},comment number {i}" for i in range(50)]
    p = profile_of("id,price,comment\n" + "\n".join(rows))
    flagged = {w["columns"][0] for w in p["warnings"] if w["type"] == "unique_id"}
    assert flagged == {"id"}


def test_sample_files_profile_cleanly():
    sales = build_profile(load_csv((SAMPLES / "sales.csv").read_bytes()))
    assert sales["summary"]["duplicate_rows"] == 5
    assert column(sales, "order_date")["kind"] == "datetime"
    survey = build_profile(load_csv((SAMPLES / "tr_survey.csv").read_bytes()))
    assert column(survey, "aylık_gelir")["kind"] == "numeric"
    assert column(survey, "anket_tarihi")["kind"] == "datetime"


# --- charts & report ------------------------------------------------------


def test_charts_cover_columns_and_overview():
    p = build_profile(load_csv((SAMPLES / "sales.csv").read_bytes()))
    ids = {c["id"] for c in build_charts(p)}
    assert {"missing", "correlation", "col-unit_price", "col-region", "col-order_date"} <= ids


def test_report_escapes_user_content():
    p = profile_of('"<script>alert(1)</script>",b\n1,2\n3,4\n')
    html = render_report(p, title="<img src=x onerror=alert(1)>")
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html
