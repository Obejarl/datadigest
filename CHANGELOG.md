# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) (0.x: the API may still change between minors).

## [0.8.0] - 2026-11-12

People's data kept apart, Spark on a cluster, statistics in plain words, and three named
sections under one roof.

### Added
- **User accounts** (`AUTH_MODE=accounts`). People sign in with an email and a password; members see
  only the datasets they uploaded, administrators see all of them and manage users on the new
  `/account` page. Salted scrypt password hashes, signed session cookies that stop working the moment
  an account is disabled, personal API tokens stored as hashes, and a first administrator from
  `ADMIN_EMAIL` / `ADMIN_PASSWORD` or `python -m datadigest.accounts add`. Migration `0007`.
  The shared `ACCESS_TOKEN` mode and running without sign-in work as before.
- **Spark on a cluster.** `SPARK_MASTER` may point at a cluster; `SPARK_DRIVER_HOST`,
  `SPARK_EXECUTOR_MEMORY` and `SPARK_CONF` configure it. `deploy/k8s-spark/` adds a Spark standalone
  cluster, a shared volume and Spark-enabled workers to the base manifests, and a new CI job deploys
  it to kind and profiles a file on the executors.
- **What stands out.** The Statistics tab and the report open with a summary in plain sentences: the
  relations that are both significant and large, then what is easy to misread (significant but tiny
  effects, averages and correlations that depend on a few outliers). A significant result with a
  small effect is marked amber instead of green, and a reading guide says how many tests were run.
- **Optimization runs respect accounts.** A run belongs to its dataset: members see and change
  only the runs on their own datasets (somebody else's run answers `404`), administrators see
  all of them.
- `STATS_MAX_ROWS`: the number of rows the statistics are computed on (default 50,000).
- `python -m datadigest`: migrate and serve in one command, with no other service to install.
- The sign-in page shows its error messages in a styled box (they were unstyled).

### Changed
- The dashboard script is one file per page (`core.js`, `index.js`, `dataset.js`, `stats.js`,
  `planner.js`, `optimize.js`, `capacity.js`, `account.js`, `login.js`) instead of one
  1,000-line file, and
  `datadigest/core/stats.py` is a package with one module per section.
- **Three sections, defined once.** Every feature now belongs to one of *Data quality* (can this
  file be trusted?), *Optimize* (what should we do with it?) and *Operations* (how do we run
  DataDigest itself?). `datadigest/sections.py` is the only place that says so: the navigation
  bar (grouped by section), the section cards on the home page, footer links for narrow screens
  (which hide the bar) and the order of the API reference are generated from it, and a test
  fails when a page or an API route has no section. Pages no longer carry their own copy of
  the navigation. The first link is now called "Datasets", and "Account" is in the bar.
- The operations-research solvers keep their own script and routes module. The capacity planner moved out of `datadigest/optimize/` to `datadigest/capacity.py`
  (`/api/capacity` is unchanged); the result shape both share is in `datadigest/envelope.py`.
- The smoke test profiles six samples at once before solving the four optimization examples.
- README screenshots show the current interface.

### Fixed
- **An idle worker no longer backs off.** The Redis client's default reply timeout (5 s) was the
  same as the worker's blocking wait on an empty queue, so every idle poll was logged as "queue
  or database unavailable" and the worker slept for up to 30 s before it looked again: a job
  that arrived then waited that long. The client now waits longer than the block.
- The Spark master in `deploy/k8s-spark/` crashed at start: Kubernetes injects
  `SPARK_MASTER_PORT=tcp://...` for a Service named `spark-master`, and Spark reads that as its
  own port. The Spark pods switch service links off.

## [0.7.1] - 2026-11-01

### Changed
- **Interface polish.** Staggered entrance animations, animated page changes (cross-document
  view transitions), a sliding tab indicator, a cursor spotlight on cards, press feedback and a
  light sweep on buttons, tiles that count up to their numbers, toasts with a timer bar that
  slide out, a top progress bar while requests are in flight, and a slow aurora behind the page.
  Spark-profiled datasets get an orange engine chip. All motion respects
  `prefers-reduced-motion`; effects live in `fx.js` and the end of `style.css`, and no layout
  depends on them.
- README screenshots show the new interface and the Statistics tab.
- The sign-in redirect test waits for the redirect itself instead of for network idle.

## [0.7.0] - 2026-10-29

### Added
- **Apache Spark profiling engine** for files that do not fit in one process's memory. It produces
  the same profile JSON as the pandas engine (so the dashboard, charts, quality score and report work
  unchanged) and is covered by a test that compares both engines on real and deliberately messy files.
  Parquet files (single files and folders) are supported. Spark is optional: `requirements-spark.txt`
  and a Java 17+ runtime; nothing else imports it.
- **Server-side files.** Set `LARGE_DATA_DIR` and files in that folder can be profiled by name:
  `GET /api/server-files`, `POST /api/server-files/{name}`, and a row of buttons on the dashboard.
  Names are validated so they cannot point outside the folder. Datasets record which engine produced
  them (`engine`, shown on the dataset page); migration `0005`.
- **Engine choice** (`--engine auto|pandas|spark` on the CLI): `auto` uses Spark for Parquet and files of
  at least `SPARK_MIN_MB` (default 100) when Spark is installed, otherwise pandas.
- `scripts/benchmark_engines.py`: times both engines and measures their peak memory on synthetic files.
- A `spark` Docker target (`docker build --target spark .`, published as `:spark` on release), and a
  `spark` CI job with a coverage gate on the Spark module.

- **Statistics tab and report section.** Variance, coefficient of variation, confidence intervals,
  three normality tests and Kolmogorov-Smirnov distribution fits; Pearson/Spearman/Kendall,
  chi-square with Cramér's V, Goodman-Kruskal gamma, Somers' d, ANOVA/Kruskal-Wallis with eta squared,
  Cohen's d and Cliff's delta; degrees of consistency (completeness, validity, format, label variants,
  duplicate-key conflicts, Cronbach's alpha); sensitivity analyses (outlier effects, bootstrap
  intervals, fragile correlations). p-values are adjusted for multiple testing. Both engines produce
  them (from a sample of at most 50,000 rows).

### Changed
- Server-side files are profiled only; optimizations need an uploaded file (`409` otherwise).

## [0.6.0] - 2026-10-29

### Added
- **Optional access control.** Set `ACCESS_TOKEN` to require a token for every page and API call:
  a sign-in page with an HttpOnly session cookie, or `Authorization: Bearer` for scripts. Wrong
  tokens are throttled. Probes, `/metrics`, the login page and static files stay open.
- **Browser tests** (Playwright, 18 tests, in CI): upload through the file input, tabs and keyboard
  shortcuts, the delete dialog, the optimizer flow, "Change inputs", the capacity page, phone-width
  layout including charts, and the sign-in flow.
- **Redis persistence** (append-only file on a volume) in Compose and Kubernetes. CI replaces the
  Redis pod with jobs queued and checks they are still processed.
- **PostgreSQL backups:** a nightly CronJob that verifies every dump, and `k8s/ops/restore-check-job.yaml`,
  which restores the newest dump into a scratch database. CI backs up and restores for real.
- **Prometheus alert rules** (9), unit-tested with `promtool` in CI, loaded and quiet on a healthy system.
- **Windows launcher** `DataDigest.bat`: install, start, open the dashboard, demo data, health check.
- Dependabot (pip, Actions, Docker) with security updates, `SECURITY.md` with private reporting,
  `CONTRIBUTING.md`, issue and pull request templates.
- Test coverage is measured (95%) and gated at 90%. The command-line tool is now tested.
- Releases publish the Docker image to GitHub Container Registry.

### Changed
- GitHub Actions are pinned to commit SHAs; the workflow token is explicitly read-only.
- Docker Compose publishes its ports on `127.0.0.1` only.
- `LICENSE` names the GitHub username as the copyright holder.

## [0.5.0] - 2026-10-24

### Added
- **Reliable queue:** at-least-once delivery with an atomic take (`BLMOVE`), acks, a visibility
  timeout, retries and a dead-letter list; a crashing handler no longer kills the worker.
- **Observability:** Prometheus metrics on the API and every worker, a Compose monitoring profile
  with Prometheus and a provisioned Grafana dashboard.

## [0.4.2] - 2026-10-24

### Added
- CI runs the full Compose stack and deploys to a real Kubernetes cluster (kind).

### Fixed
- Workers waited for Redis and PostgreSQL by crashing; they now back off and retry.

## [0.4.1] - 2026-10-24

### Fixed
- Pages scrolled sideways on phones (a screen-reader label escaped its scroll box).
- Browsers served stale CSS after an update: HTML is revalidated and assets are versioned.
- "Change inputs" reopens the form with the run's own parameters.

### Added
- Model size limits, a deeper container smoke test, choosable task and destination columns.

## [0.4.0] - 2026-10-23

### Added
- **Operations research:** production planning (LP/MIP), transportation, assignment (Hungarian)
  and budget allocation (0/1 MIP) on HiGHS, with shadow prices, a comparison against the usual
  rule of thumb, and an optimization report.
- **Capacity planning** for the workers with an M/M/c queueing model and a suggested HPA.

## [0.3.0] - 2026-10-23

### Added
- Re-run, recovery of stuck jobs, bundled sample datasets, a data preview tab, multi-file upload,
  and security headers.

## [0.2.0] - 2026-10-23

### Added
- A 0-100 data-quality score, `/api/stats`, and a redesigned dark dashboard and report.

## [0.1.0] - 2026-10-23

### Added
- CSV profiling (encoding and delimiter detection, column statistics, correlations, warnings),
  an HTML report and a command-line tool.
- REST API, PostgreSQL models with Alembic migrations, a Redis queue with workers, a web
  dashboard, Docker, Docker Compose, Kubernetes manifests and CI.

[0.8.0]: https://github.com/Obejarl/datadigest/releases/tag/v0.8.0
[0.7.1]: https://github.com/Obejarl/datadigest/releases/tag/v0.7.1
[0.7.0]: https://github.com/Obejarl/datadigest/releases/tag/v0.7.0
[0.6.0]: https://github.com/Obejarl/datadigest/releases/tag/v0.6.0
[0.5.0]: https://github.com/Obejarl/datadigest/commits/7763142
