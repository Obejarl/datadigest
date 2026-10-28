"""Offline usage, no services needed.

python -m datadigest.cli report data.csv -o report.html
python -m datadigest.cli profile data.csv
python -m datadigest.cli report big.csv --engine spark     # needs requirements-spark.txt and Java
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from datadigest.core.engines import ENGINES, profile_path
from datadigest.core.loader import LoadError
from datadigest.core.report import render_report

ENGINE_HELP = "auto: Spark for Parquet and files over SPARK_MIN_MB (when installed), otherwise pandas"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datadigest", description="Profile a CSV file.")
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="write an HTML report")
    report.add_argument("input", type=Path)
    report.add_argument("-o", "--output", type=Path, help="default: <input>.report.html")
    report.add_argument("--title")
    report.add_argument("--engine", choices=ENGINES, default="auto", help=ENGINE_HELP)

    profile = sub.add_parser("profile", help="print the profile as JSON")
    profile.add_argument("input", type=Path)
    profile.add_argument("--engine", choices=ENGINES, default="auto", help=ENGINE_HELP)

    args = parser.parse_args(argv)
    try:
        result = profile_path(args.input, args.engine)
    except (OSError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.command == "profile":
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    output = args.output or args.input.with_suffix(".report.html")
    output.write_text(render_report(result, args.title or args.input.name), encoding="utf-8")
    s = result["summary"]
    print(f"{output}  ({s['rows']} rows, {s['columns']} columns, {len(result['warnings'])} warnings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
