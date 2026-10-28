# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) (0.x: the API may still change between minors).

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

[0.6.0]: https://github.com/Obejarl/datadigest/releases/tag/v0.6.0
[0.5.0]: https://github.com/Obejarl/datadigest/commits/7763142
