"""Time and measure the memory of the pandas and the Spark profiling engines on growing files.

    python scripts/benchmark_engines.py 100000 1000000 5000000
    python scripts/benchmark_engines.py 1000000 --engines spark --output docs/BENCHMARK.md

Needs requirements-spark.txt (pyspark, psutil) and a Java runtime. Each run happens in its own
process, so the peak memory (the process plus its children, which includes Spark's JVM) belongs
to that run alone. The data is synthetic: 8 columns of every kind the profiler tells apart.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parent.parent
CHUNK_ROWS = 500_000
REGIONS = np.array(["North", "South", "East", "West", "Central"])


def write_csv(path: Path, rows: int, seed: int = 7) -> None:
    """A sales-like file, written in chunks so that making the data never needs much memory."""
    rng = np.random.default_rng(seed)
    start = np.datetime64("2023-01-01")
    written = 0
    while written < rows:
        n = min(CHUNK_ROWS, rows - written)
        units = rng.integers(1, 20, n)
        price = rng.gamma(2.0, 20.0, n).round(2)
        frame = pd.DataFrame(
            {
                "order_id": np.arange(written, written + n),
                "order_date": (start + rng.integers(0, 900, n).astype("timedelta64[D]")).astype(str),
                "region": REGIONS[rng.integers(0, len(REGIONS), n)],
                "units": units,
                "unit_price": price,
                "discount_pct": rng.choice([0.0, 5.0, 10.0, 15.0], n),
                "revenue": (units * price).round(2),
                "returning": rng.choice(["True", "False"], n),
            }
        )
        frame.loc[rng.random(n) < 0.03, "unit_price"] = np.nan
        frame.to_csv(path, mode="a", header=written == 0, index=False)
        written += n


def run_engine(engine: str, path: Path) -> dict:
    """Profile ``path`` in a fresh process; report wall time and the peak memory of its process tree."""
    code = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from datadigest.config import Settings\n"
        "from datadigest.core.engines import profile_path\n"
        "t = time.perf_counter()\n"
        "s = Settings(max_rows=10**12, spark_driver_memory='4g')\n"
        "p = profile_path(Path(sys.argv[1]), sys.argv[2], s)\n"
        "print(json.dumps({'seconds': time.perf_counter() - t, 'rows': p['summary']['rows'],\n"
        "                  'score': p['summary']['quality']['score']}))\n"
    )
    started = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(path), engine],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    peak = 0
    watcher = psutil.Process(proc.pid)
    while proc.poll() is None:
        try:
            tree = [watcher, *watcher.children(recursive=True)]
            peak = max(peak, sum(p.memory_info().rss for p in tree if p.is_running()))
        except psutil.Error:
            pass
        time.sleep(0.05)
    # Spark's launcher may print its own lines (e.g. process clean-up on Windows); keep only our JSON.
    out = [line for line in proc.stdout.read().splitlines() if line.startswith("{")]
    wall = time.perf_counter() - started
    if proc.returncode != 0 or not out:
        return {"failed": True, "wall": wall, "peak_mb": peak / 2**20}
    result = json.loads(out[-1])
    return {**result, "wall": wall, "peak_mb": peak / 2**20, "failed": False}


def table(results: list[dict]) -> str:
    lines = [
        "| Rows | File | Engine | Profile time | Wall time (incl. start-up) | Peak memory |",
        "|---:|---:|---|---:|---:|---:|",
    ]
    for r in results:
        if r["failed"]:
            lines.append(
                f"| {r['rows']:,} | {r['mb']:.0f} MB | {r['engine']} | failed "
                f"| {r['wall']:.1f} s | {r['peak_mb']:,.0f} MB |"
            )
        else:
            lines.append(
                f"| {r['rows']:,} | {r['mb']:.0f} MB | {r['engine']} | {r['seconds']:.1f} s "
                f"| {r['wall']:.1f} s | {r['peak_mb']:,.0f} MB |"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("rows", type=int, nargs="+", help="row counts to test")
    parser.add_argument("--engines", nargs="+", default=["pandas", "spark"], choices=["pandas", "spark"])
    parser.add_argument("--output", type=Path, help="also write the table to this Markdown file")
    args = parser.parse_args()

    results = []
    with tempfile.TemporaryDirectory() as folder:
        for rows in args.rows:
            path = Path(folder) / f"bench_{rows}.csv"
            print(f"writing {rows:,} rows ...", flush=True)
            write_csv(path, rows)
            mb = path.stat().st_size / 2**20
            for engine in args.engines:
                print(f"  {engine} ...", end=" ", flush=True)
                result = {"rows": rows, "mb": mb, "engine": engine, **run_engine(engine, path)}
                print(
                    "failed"
                    if result["failed"]
                    else f"{result['seconds']:.1f} s, {result['peak_mb']:,.0f} MB"
                )
                results.append(result)
            path.unlink()

    text = table(results)
    print("\n" + text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
