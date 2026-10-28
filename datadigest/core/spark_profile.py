"""Profile a big CSV or Parquet file with Apache Spark.

Same contract as ``core.profile.build_profile``: one JSON-serializable dict, so the dashboard,
charts and HTML report work unchanged. The difference is where the work happens. pandas loads
the whole file into one process's memory; Spark reads it in partitions and computes each
statistic as a distributed aggregation, so only the small results ever reach Python.

Spark is an optional dependency (``pip install -r requirements-spark.txt``, plus a Java
runtime), so pyspark is imported inside functions and the rest of the package never needs it.

Where the numbers can differ from the pandas engine, on purpose:
- ``unique`` is exact, but quantiles switch to Spark's approximate algorithm above
  ``EXACT_QUANTILE_ROWS`` rows (the exact one keeps every distinct value in memory);
- rows with a wrong number of fields are padded or cut instead of failing the whole file;
- quoted line breaks inside a field are not supported (they would stop Spark from splitting
  the file into parallel partitions).
"""

from __future__ import annotations

import importlib.util
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np

from datadigest.config import Settings, get_settings
from datadigest.core import profile as shared
from datadigest.core.loader import _DECIMAL_COMMA, LoadError, decode, detect_delimiter

SAMPLE_BYTES = 256 * 1024
EXACT_QUANTILE_ROWS = 5_000_000
QUANTILES = [0.25, 0.5, 0.75]
APPROX_QUANTILE_ACCURACY = 100_000

# What pandas.read_csv treats as missing by default.
NA_TOKENS = [
    "", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND", "1.#QNAN",
    "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null",
]  # fmt: skip
# pandas only gives a column the bool dtype for these spellings, and only without missing values.
PANDAS_BOOLEANS = ("True", "TRUE", "true", "False", "FALSE", "false")
NUMBER = r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$"
INTEGER = r"^[+-]?\d+$"
DATE_LIKE = r"\d[-./]\d"
# The same formats as profile.DATE_FORMATS, in Spark's pattern language (single letters
# accept both "5" and "05", like strptime does).
SPARK_DATE_FORMATS = (
    "yyyy-M-d",
    "yyyy-M-d H:m:s",
    "yyyy-M-d'T'H:m:s",
    "d.M.yyyy",
    "d.M.yyyy H:m",
    "d/M/yyyy",
    "M/d/yyyy",
)
# Spark's CSV reader only accepts a few charsets (not cp1254, the Turkish Windows one). Such files
# are read as ISO-8859-1, which maps every byte to a character, and the few characters where
# cp1254 differs (Ğ, İ, Ş, ğ, ı, ş and the 0x80-0x9F block) are translated afterwards.
SPARK_CHARSETS = {"utf-8": "UTF-8", "utf-8-sig": "UTF-8", "cp1254": "ISO-8859-1", "latin-1": "ISO-8859-1"}


def _cp1254_fixes() -> dict[str, str]:
    fixes = {}
    for byte in range(0x80, 0x100):
        try:
            fixed = bytes([byte]).decode("cp1254")
        except UnicodeDecodeError:
            continue
        if fixed != chr(byte):
            fixes[chr(byte)] = fixed
    return fixes


CP1254_FIXES = _cp1254_fixes()
PARQUET_SUFFIX = ".parquet"


def spark_available() -> bool:
    """pyspark is installed and a Java runtime can be found (Spark runs on the JVM)."""
    has_java = shutil.which("java") is not None or bool(os.environ.get("JAVA_HOME"))
    return importlib.util.find_spec("pyspark") is not None and has_java


def _check_windows_path() -> None:
    """Spark's Windows launcher cannot start from a folder with non-ASCII characters in its path."""
    if os.name != "nt":
        return
    import pyspark

    home = os.environ.get("SPARK_HOME") or str(Path(pyspark.__file__).parent)
    if not home.isascii():
        raise LoadError(
            "Spark cannot start from a path with non-ASCII characters on Windows. "
            "Point SPARK_HOME to a link or copy of the pyspark folder with an ASCII path."
        )


def get_session(settings: Settings | None = None):
    """The shared local (or cluster) SparkSession; created on first use and reused after."""
    settings = settings or get_settings()
    if not spark_available():
        raise LoadError(
            "The Spark engine needs pyspark and a Java runtime (pip install -r requirements-spark.txt)"
        )
    if settings.spark_home:
        os.environ["SPARK_HOME"] = settings.spark_home
    _check_windows_path()
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.master(settings.spark_master)
        .appName("datadigest")
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.shuffle.partitions", str(settings.spark_shuffle_partitions))
        # Timestamps are rendered in UTC so a profile does not depend on the server's time zone.
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.legacy.timeParserPolicy", "CORRECTED")
    )
    if settings.spark_driver_memory:
        builder = builder.config("spark.driver.memory", settings.spark_driver_memory)
    try:
        session = builder.getOrCreate()
    except Exception as exc:  # py4j and launcher errors are not worth exposing as types
        raise LoadError(f"Could not start Spark: {str(exc).splitlines()[0][:200]}") from exc
    session.sparkContext.setLogLevel("ERROR")
    return session


def _disk_bytes(path: Path) -> int:
    if path.is_dir():  # a Parquet dataset is a folder of part files
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return path.stat().st_size


def _sniff(path: Path) -> tuple[str, str]:
    """Encoding and delimiter from the first bytes, the same way the pandas loader decides."""
    with path.open("rb") as handle:
        head = handle.read(SAMPLE_BYTES)
    if not head.strip():
        raise LoadError("File is empty")
    cut = head.rfind(b"\n")
    if cut > 0:  # do not end the sample in the middle of a multi-byte character
        head = head[: cut + 1]
    text, encoding = decode(head)
    return encoding, detect_delimiter(text)


def _unique_names(names: list[str]) -> list[str]:
    """Strip names and de-duplicate them the way pandas does ('x', 'x.1', 'x.2')."""
    seen: dict[str, int] = {}
    result = []
    for raw in names:
        name = raw.lstrip("﻿").strip()
        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if count == 0 else f"{name}.{count}")
    return result


def _read(spark, path: Path):
    """The file as a DataFrame of strings with internal column names c0, c1, ... and the real names."""
    from pyspark.sql import functions as F

    if path.suffix.lower() == PARQUET_SUFFIX:
        raw = spark.read.parquet(str(path))
        header = list(raw.columns)
        raw = raw.select([F.col(f"`{c}`").cast("string").alias(c) for c in header])
        encoding, delimiter = "parquet", ""
    else:
        encoding, delimiter = _sniff(path)
        options = {
            "sep": delimiter,
            "encoding": SPARK_CHARSETS[encoding],
            "quote": '"',
            "escape": '"',
            "mode": "PERMISSIVE",
        }
        raw = spark.read.csv(str(path), header=True, **options)
        # Spark renames headers that differ only in case ('Name', 'name'); pandas does not.
        # So the real header comes from the first line, read as data.
        first_line = spark.read.csv(str(path), header=False, **options).limit(1).first()
        header = [
            first_line[i] if i < len(first_line) and first_line[i] is not None else f"Unnamed: {i}"
            for i in range(len(raw.columns))
        ]
    names = _unique_names(header)
    if not names:
        raise LoadError("File has no data rows")
    internal = [f"c{i}" for i in range(len(names))]
    values = [F.col(c) for c in internal]
    if encoding == "cp1254":
        names = [n.translate(str.maketrans(CP1254_FIXES)) for n in names]
        values = [F.translate(v, "".join(CP1254_FIXES), "".join(CP1254_FIXES.values())) for v in values]
    cleaned = raw.toDF(*internal).select(
        *[
            F.when(v.isin(NA_TOKENS), F.lit(None)).otherwise(v).alias(c)
            for v, c in zip(values, internal, strict=True)
        ]
    )
    return cleaned, internal, names, encoding, delimiter


STAT_KEYS = ("nn", "num", "int", "bool", "date", "tf", "uniq", "comma", "dec")


def _first_pass(df, columns: list[str], delimiter: str) -> tuple[int, list[dict[str, Any]]]:
    """Row count plus, per column, the counts that decide its kind (one scan of the data)."""
    from pyspark.sql import functions as F

    aggs = [F.count(F.lit(1)).alias("rows")]
    for i, c in enumerate(columns):
        col = F.col(c)
        trimmed = F.trim(col)
        aggs += [
            F.count(col).alias(f"nn{i}"),
            F.count(F.when(trimmed.rlike(NUMBER), 1)).alias(f"num{i}"),
            F.count(F.when(trimmed.rlike(INTEGER), 1)).alias(f"int{i}"),
            F.count(F.when(F.lower(trimmed).isin(*sorted(shared.BOOLEAN_WORDS)), 1)).alias(f"bool{i}"),
            F.count(F.when(trimmed.rlike(DATE_LIKE), 1)).alias(f"date{i}"),
            F.count(F.when(col.isin(*PANDAS_BOOLEANS), 1)).alias(f"tf{i}"),
            F.countDistinct(col).alias(f"uniq{i}"),
        ]
        if delimiter != ",":
            aggs += [
                F.count(F.when(trimmed.contains(","), 1)).alias(f"comma{i}"),
                F.count(F.when(trimmed.rlike(_DECIMAL_COMMA.pattern), 1)).alias(f"dec{i}"),
            ]
    row = df.agg(*aggs).first().asDict()
    stats = [{key: row.get(f"{key}{i}", 0) for key in STAT_KEYS} for i in range(len(columns))]
    return row["rows"], stats


def _date_formats(df, columns: list[str], stats: list[dict[str, Any]]) -> None:
    """Second scan, only over columns that could be dates: how many values each format parses."""
    from pyspark.sql import functions as F

    candidates = [
        i
        for i, s in enumerate(stats)
        if s["nn"] and s["num"] != s["nn"] and s["bool"] != s["nn"] and s["date"] == s["nn"]
    ]
    if not candidates:
        return
    aggs = [
        F.count(F.try_to_timestamp(F.trim(F.col(columns[i])), F.lit(fmt))).alias(f"f{i}_{k}")
        for i in candidates
        for k, fmt in enumerate(SPARK_DATE_FORMATS)
    ]
    row = df.agg(*aggs).first().asDict()
    for i in candidates:
        for k in range(len(SPARK_DATE_FORMATS)):
            if row[f"f{i}_{k}"] / stats[i]["nn"] >= 0.9:
                stats[i]["date_format"] = k
                break


def _kind(s: dict[str, Any]) -> str:
    """The same decision order as profile.infer_kind, from the counts of the first scan."""
    nn = s["nn"]
    if nn == 0 or s["num"] == nn:
        return "numeric"
    if s["comma"] and s["dec"] == nn:
        return "numeric"  # '1.234,56' style numbers, like the pandas loader's decimal-comma coercion
    if s["bool"] == nn and s["uniq"] <= 2:
        return "boolean"
    if "date_format" in s:
        return "datetime"
    if s["uniq"] <= 50 or s["uniq"] / nn <= 0.5:
        return "categorical"
    return "text"


def _typed(columns: list[str], stats: list[dict[str, Any]], kinds: list[str]):
    """Each column converted to the type of its kind, so later scans can aggregate it."""
    from pyspark.sql import functions as F

    exprs = []
    for c, s, kind in zip(columns, stats, kinds, strict=True):
        text = F.trim(F.col(c))
        if kind == "numeric":
            if s["num"] != s["nn"] and s["comma"]:
                text = F.regexp_replace(F.regexp_replace(text, r"\.", ""), ",", ".")
            exprs.append(text.try_cast("double").alias(c))
        elif kind == "datetime":
            exprs.append(F.try_to_timestamp(text, F.lit(SPARK_DATE_FORMATS[s["date_format"]])).alias(c))
        else:
            exprs.append(F.col(c))
    return exprs


def _numeric_stats(typed, names: list[str], rows: int) -> dict[str, dict[str, Any]]:
    from pyspark.sql import functions as F

    exact = rows <= EXACT_QUANTILE_ROWS
    aggs = []
    for c in names:
        x = F.col(c)
        if exact:
            quantiles = F.percentile(x, QUANTILES)
        else:
            quantiles = F.percentile_approx(x, QUANTILES, APPROX_QUANTILE_ACCURACY)
        aggs += [
            F.count(x).alias(f"n_{c}"),
            F.mean(x).alias(f"mean_{c}"),
            F.stddev_samp(x).alias(f"std_{c}"),
            F.min(x).alias(f"min_{c}"),
            F.max(x).alias(f"max_{c}"),
            F.skewness(x).alias(f"skew_{c}"),
            F.count(F.when(x == 0, 1)).alias(f"zeros_{c}"),
            quantiles.alias(f"q_{c}"),
        ]
    row = typed.agg(*aggs).first().asDict()

    result = {}
    for c in names:
        n = row[f"n_{c}"]
        if n == 0:
            result[c] = {}
            continue
        q1, median, q3 = row[f"q_{c}"]
        skew = row[f"skew_{c}"]
        if n > 2 and skew is not None and not math.isnan(skew):
            # Spark's skewness is the population one; pandas' is the sample-adjusted estimate.
            skew = skew * math.sqrt(n * (n - 1)) / (n - 2)
        else:
            skew = None
        result[c] = {
            "n": n,
            "mean": shared._num(row[f"mean_{c}"]),
            "std": shared._num(row[f"std_{c}"]),
            "min": row[f"min_{c}"],
            "p25": q1,
            "median": median,
            "p75": q3,
            "max": row[f"max_{c}"],
            "skew": shared._num(skew) if n > 2 else None,
            "zeros": row[f"zeros_{c}"],
        }
    return result


def _bucket(x, edges: np.ndarray, lo: float, hi: float):
    """Histogram bin of ``x``, computed exactly like numpy.histogram (including its edge fix-ups)."""
    from pyspark.sql import functions as F

    bins = len(edges) - 1
    guess = F.least(F.lit(bins - 1), F.floor((x - F.lit(lo)) * F.lit(bins / (hi - lo))).cast("int"))
    table = F.array(*[F.lit(float(e)) for e in edges])
    below = x < F.element_at(table, guess + 1)
    above = (x >= F.element_at(table, guess + 2)) & (guess != bins - 1)
    bucket = guess - F.when(below, 1).otherwise(0) + F.when(above & ~below, 1).otherwise(0)
    return F.when(x.isNotNull(), bucket)  # least() skips nulls, so a missing value would land in the last bin


def _outliers_and_histograms(typed, numeric: dict[str, dict[str, Any]]) -> None:
    """Fill in IQR outlier counts and histogram buckets (one scan each, for all numeric columns)."""
    from pyspark.sql import functions as F

    names = [c for c, s in numeric.items() if s]
    if not names:
        return

    fences = {}
    for c in names:
        s = numeric[c]
        iqr = s["p75"] - s["p25"]
        fences[c] = (s["p25"] - 1.5 * iqr, s["p75"] + 1.5 * iqr) if iqr > 0 else None
    outlier_aggs = [
        F.count(F.when((F.col(c) < fence[0]) | (F.col(c) > fence[1]), 1)).alias(f"out_{c}")
        for c, fence in fences.items()
        if fence
    ]
    outliers = typed.agg(*outlier_aggs).first().asDict() if outlier_aggs else {}

    parts, layouts = [], {}
    for i, c in enumerate(names):
        s = numeric[c]
        bins = int(min(30, max(5, math.sqrt(s["n"]))))
        lo, hi = float(s["min"]), float(s["max"])
        if lo == hi:  # numpy widens an empty range the same way
            lo, hi = lo - 0.5, hi + 0.5
        edges = np.linspace(lo, hi, bins + 1)
        layouts[i] = (c, bins, edges)
        parts.append(F.struct(F.lit(i).alias("i"), _bucket(F.col(c), edges, lo, hi).alias("b")))
    grouped = (
        typed.select(F.explode(F.array(*parts)).alias("p"))
        .select(F.col("p.i").alias("i"), F.col("p.b").alias("b"))
        .where(F.col("b").isNotNull())
        .groupBy("i", "b")
        .count()
        .collect()
    )
    counts = {i: [0] * layouts[i][1] for i in layouts}
    for row in grouped:
        counts[row["i"]][max(0, row["b"])] = row["count"]

    for i, (c, _bins, edges) in layouts.items():
        n_out = outliers.get(f"out_{c}", 0)
        numeric[c]["outliers"] = n_out
        numeric[c]["outliers_pct"] = shared._pct(n_out, numeric[c]["n"])
        numeric[c]["histogram"] = {"counts": counts[i], "edges": [shared._num(e) for e in edges]}


def _top_values(typed, names: list[str], non_null: dict[str, int]) -> dict[str, dict[str, Any]]:
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    if not names:
        return {}
    parts = [F.struct(F.lit(i).alias("i"), F.col(c).alias("v")) for i, c in enumerate(names)]
    counts = (
        typed.select(F.explode(F.array(*parts)).alias("p"))
        .select(F.col("p.i").alias("i"), F.col("p.v").alias("v"))
        .where(F.col("v").isNotNull())
        .groupBy("i", "v")
        .count()
    )
    ranked = counts.withColumn(
        "r", F.row_number().over(Window.partitionBy("i").orderBy(F.desc("count"), F.asc("v")))
    ).where(F.col("r") <= shared.TOP_N)
    top: dict[int, list[dict[str, Any]]] = {i: [] for i in range(len(names))}
    for row in sorted(ranked.collect(), key=lambda r: (r["i"], r["r"])):
        top[row["i"]].append({"value": str(row["v"]), "count": int(row["count"])})
    return {
        c: {"top": top[i], "other_count": non_null[c] - sum(t["count"] for t in top[i])}
        for i, c in enumerate(names)
    }


def _datetime_stats(typed, names: list[str]) -> dict[str, dict[str, Any]]:
    from pyspark.sql import functions as F

    if not names:
        return {}
    stamp = "yyyy-MM-dd'T'HH:mm:ss"
    aggs = []
    for c in names:
        x = F.col(c)
        aggs += [
            F.count(x).alias(f"n_{c}"),
            F.countDistinct(x).alias(f"u_{c}"),
            F.date_format(F.min(x), stamp).alias(f"min_{c}"),
            F.date_format(F.max(x), stamp).alias(f"max_{c}"),
            (F.max(x).cast("long") - F.min(x).cast("long")).alias(f"span_{c}"),
        ]
    row = typed.agg(*aggs).first().asDict()

    result = {}
    for c in names:
        n = row[f"n_{c}"]
        if n == 0:
            result[c] = {"n": 0, "unique": 0}
            continue
        span_days = row[f"span_{c}"] // 86400  # whole days, like Timedelta.days
        freq, fmt = ("M", "yyyy-MM") if span_days > 60 else ("D", "yyyy-MM-dd")
        timeline = (
            typed.where(F.col(c).isNotNull())
            .groupBy(F.date_format(F.col(c), fmt).alias("label"))
            .count()
            .orderBy("label")
            .collect()
        )
        result[c] = {
            "n": n,
            "unique": row[f"u_{c}"],
            "min": row[f"min_{c}"],
            "max": row[f"max_{c}"],
            "span_days": int(span_days),
            "timeline": {
                "freq": freq,
                "labels": [t["label"] for t in timeline],
                "counts": [int(t["count"]) for t in timeline],
            },
        }
    return result


def _text_stats(typed, names: list[str]) -> dict[str, dict[str, Any]]:
    from pyspark.sql import functions as F

    if not names:
        return {}
    aggs = []
    for c in names:
        aggs += [F.avg(F.length(F.col(c))).alias(f"avg_{c}"), F.max(F.length(F.col(c))).alias(f"max_{c}")]
    row = typed.agg(*aggs).first().asDict()
    return {
        c: {
            "avg_length": shared._num(row[f"avg_{c}"]),
            "max_length": shared._num(row[f"max_{c}"]),
            "examples": [r[0] for r in typed.where(F.col(c).isNotNull()).select(c).limit(3).collect()],
        }
        for c in names
    }


def _correlations(typed, numeric: dict[str, dict[str, Any]], display: dict[str, str]):
    from pyspark.sql import functions as F

    usable = [c for c, s in numeric.items() if s and s["std"] and s["std"] > 0]
    usable = usable[: shared.MAX_CORRELATION_COLUMNS]
    if len(usable) < 2:
        return None
    pairs = [(a, b) for i, a in enumerate(usable) for b in usable[i + 1 :]]
    row = typed.agg(*[F.corr(F.col(a), F.col(b)).alias(f"r{k}") for k, (a, b) in enumerate(pairs)]).first()
    index = {c: i for i, c in enumerate(usable)}
    matrix = [[1.0 if i == j else None for j in range(len(usable))] for i in range(len(usable))]
    for k, (a, b) in enumerate(pairs):
        value = shared._num(row[f"r{k}"])
        matrix[index[a]][index[b]] = matrix[index[b]][index[a]] = value
    return {"columns": [display[c] for c in usable], "matrix": matrix}


def _preview(df, names: list[str], columns: list[str]) -> dict[str, Any]:
    rows = [
        [None if v is None else str(v)[: shared.PREVIEW_CELL_CHARS] for v in record]
        for record in df.select(*columns).limit(shared.PREVIEW_ROWS).collect()
    ]
    return {"columns": names, "rows": rows}


def build_profile_spark(path: Path, settings: Settings | None = None) -> dict[str, Any]:
    """Profile the file at ``path`` (CSV, TSV, TXT or Parquet) with Spark."""
    spark = get_session(settings)
    cleaned, columns, names, encoding, delimiter = _read(spark, Path(path))
    display = dict(zip(columns, names, strict=True))
    cleaned = cleaned.persist()  # every scan below re-reads it; parse the file once
    try:
        rows, stats = _first_pass(cleaned, columns, delimiter)
        if rows == 0:
            raise LoadError("File has no data rows")
        _date_formats(cleaned, columns, stats)
        kinds = [_kind(s) for s in stats]
        typed = cleaned.select(*_typed(columns, stats, kinds))

        by_kind = {k: [c for c, kind in zip(columns, kinds, strict=True) if kind == k] for k in set(kinds)}
        numeric = _numeric_stats(typed, by_kind.get("numeric", []), rows)
        _outliers_and_histograms(typed, numeric)
        non_null = {c: s["nn"] for c, s in zip(columns, stats, strict=True)}
        categorical = _top_values(
            typed, by_kind.get("categorical", []) + by_kind.get("boolean", []), non_null
        )
        datetimes = _datetime_stats(typed, by_kind.get("datetime", []))
        texts = _text_stats(typed, by_kind.get("text", []))
        correlations = _correlations(typed, numeric, display)
        duplicates = rows - typed.distinct().count()
        preview = _preview(cleaned, names, columns)
    finally:
        cleaned.unpersist()

    profile_columns = []
    for c, s, kind in zip(columns, stats, kinds, strict=True):
        missing, unique = rows - s["nn"], s["uniq"]
        extra: dict[str, Any] = {}
        if kind == "numeric":
            extra = {
                k: shared._num(v) if k in ("min", "p25", "median", "p75", "max") else v
                for k, v in numeric[c].items()
                if k != "n"
            }
            dtype = "int64" if s["int"] == s["nn"] and s["nn"] else "float64"
        elif kind == "datetime":
            d = datetimes[c]
            # values that no date format parsed count as missing, as in pandas
            missing, unique = rows - d["n"], d["unique"]
            extra = {k: v for k, v in d.items() if k not in ("n", "unique")}
            dtype = "str"
        elif kind in ("categorical", "boolean"):
            extra = categorical[c]
            dtype = "bool" if kind == "boolean" and s["tf"] == s["nn"] == rows else "str"
        else:
            extra, dtype = texts[c], "str"
        profile_columns.append(
            {
                "name": display[c],
                "kind": kind,
                "dtype": dtype,
                "missing": missing,
                "missing_pct": shared._pct(missing, rows),
                "unique": unique,
                "unique_pct": shared._pct(unique, rows - missing),
                **extra,
            }
        )

    missing_cells = sum(c["missing"] for c in profile_columns)
    missing_pct = shared._pct(missing_cells, rows * len(profile_columns))
    warnings = shared._warnings(profile_columns, correlations, duplicates, rows)
    kind_counts: dict[str, int] = {}
    for c in profile_columns:
        kind_counts[c["kind"]] = kind_counts.get(c["kind"], 0) + 1
    return {
        "summary": {
            "rows": rows,
            "columns": len(profile_columns),
            "missing_cells": missing_cells,
            "missing_cells_pct": missing_pct,
            "duplicate_rows": duplicates,
            # Not the size in memory (Spark never holds the whole file): the size on disk.
            "memory_bytes": _disk_bytes(Path(path)),
            "kinds": kind_counts,
            "encoding": encoding,
            "delimiter": delimiter,
            "truncated": False,
            "engine": "spark",
            "quality": shared.quality_score(missing_pct, shared._pct(duplicates, rows), warnings),
        },
        "columns": profile_columns,
        "correlations": correlations,
        "warnings": warnings,
        "preview": preview,
    }
