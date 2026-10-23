"""Turn raw uploaded bytes into a DataFrame.

Real-world CSV files are messy: Excel in a Turkish locale writes ``;``-separated
files in cp1254 with decimal commas. We detect encoding and delimiter instead of
assuming ``utf-8`` and ``,``.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pandas as pd

# cp1254 leaves a few bytes undefined, so it can fail; latin-1 never fails and is the last resort.
ENCODINGS = ("utf-8-sig", "cp1254", "latin-1")
DELIMITERS = (",", ";", "\t", "|")
SAMPLE_LINES = 50

_DECIMAL_COMMA = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d+$|^-?\d+,\d+$|^-?\d+$")


class LoadError(ValueError):
    """The file could not be read as a table. The message is safe to show to users."""


@dataclass
class LoadedTable:
    df: pd.DataFrame
    encoding: str
    delimiter: str
    truncated: bool


def decode(raw: bytes) -> tuple[str, str]:
    for encoding in ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8"
        return text, encoding
    raise LoadError("Could not decode file")  # unreachable: latin-1 accepts any byte


def detect_delimiter(text: str) -> str:
    """Pick the delimiter that appears the same, non-zero number of times on most lines."""
    lines = [line for line in text.splitlines()[:SAMPLE_LINES] if line.strip()]
    if not lines:
        raise LoadError("File is empty")

    best, best_score = ",", (0.0, 0)
    for delimiter in DELIMITERS:
        counts = [line.count(delimiter) for line in lines]
        mode = max(set(counts), key=counts.count)
        if mode == 0:
            continue
        score = (counts.count(mode) / len(counts), mode)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def _coerce_decimal_comma(df: pd.DataFrame) -> pd.DataFrame:
    """Convert text columns like '1.234,56' to floats (common in Turkish/European exports)."""
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            continue
        values = series.dropna().astype(str).str.strip()
        if values.empty or not values.str.contains(",").any():
            continue
        if values.str.match(_DECIMAL_COMMA).all():
            normalized = values.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(normalized.reindex(series.index), errors="coerce")
    return df


def load_csv(raw: bytes, max_rows: int = 200_000) -> LoadedTable:
    if not raw.strip():
        raise LoadError("File is empty")

    text, encoding = decode(raw)
    delimiter = detect_delimiter(text)
    try:
        df = pd.read_csv(io.StringIO(text), sep=delimiter, nrows=max_rows + 1)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise LoadError(f"Could not parse CSV: {exc}") from exc

    if df.empty or len(df.columns) == 0:
        raise LoadError("File has no data rows")

    truncated = len(df) > max_rows
    if truncated:
        df = df.iloc[:max_rows]

    df.columns = [str(c).strip() for c in df.columns]
    if delimiter != ",":
        df = _coerce_decimal_comma(df)
    return LoadedTable(df=df, encoding=encoding, delimiter=delimiter, truncated=truncated)
