"""Offline usage, no services needed.

python -m datadigest.cli report data.csv -o report.html
python -m datadigest.cli profile data.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from datadigest.core.loader import LoadError, load_csv
from datadigest.core.profile import build_profile
from datadigest.core.report import render_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datadigest", description="Profile a CSV file.")
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="write an HTML report")
    report.add_argument("input", type=Path)
    report.add_argument("-o", "--output", type=Path, help="default: <input>.report.html")
    report.add_argument("--title")

    profile = sub.add_parser("profile", help="print the profile as JSON")
    profile.add_argument("input", type=Path)

    args = parser.parse_args(argv)
    try:
        result = build_profile(load_csv(args.input.read_bytes()))
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
