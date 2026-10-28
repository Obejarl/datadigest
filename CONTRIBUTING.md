# Contributing

Thanks for looking. Issues and pull requests are welcome.

## Set up

```bash
python -m venv .venv && .venv\Scripts\activate     # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn datadigest.api.main:app --reload
```

On Windows, `DataDigest.bat start` does all of that.

## Before you open a pull request

```bash
ruff check . && ruff format --check .
pytest --cov=datadigest --cov-fail-under=90     # unit tests, SQLite + fakeredis
python scripts/check_manifests.py                # Kubernetes and Compose cross-checks
```

The Spark engine has its own tests (they need Java 17 or newer and `pip install -r requirements-spark.txt`,
and are skipped otherwise):

```bash
pytest -m spark --cov=datadigest.core.spark_profile --cov-config=scripts/coveragerc-spark
```

On Windows, Spark cannot start from a folder whose path has non-ASCII characters (for example `Masaüstü`).
Create a link with an ASCII path and point `SPARK_HOME` at it:
`mklink /J C:\pyspark_home <venv>\Lib\site-packages\pyspark`, then `set SPARK_HOME=C:\pyspark_home`.
Folder-shaped Parquet datasets also need Hadoop's `winutils.exe` on Windows; Linux and CI do not.

CI additionally runs integration tests on real PostgreSQL and Redis, the Docker image, the full
Compose stack, and a deployment to a kind cluster. If you change the schema, add an Alembic migration
(`migrations/versions/`) and check that it upgrades and downgrades.

## Conventions

- Solvers (`datadigest/optimize`) and profiling (`datadigest/core`) stay pure: no database, no HTTP.
- The pandas and Spark engines return the same profile. A change to one needs the same change in the
  other; `tests/test_spark_profile.py` compares them on real files.
- A new optimizer returns the shared result envelope (`optimize/common.py`) so the dashboard and the
  report render it without new UI code. Tests should compare it with brute force or re-solve to verify
  duals.
- Anything derived from an uploaded file reaches the page through `textContent` or Jinja autoescape.
- Keep the README and `docs/LEARNING.md` in step with behavior changes.
