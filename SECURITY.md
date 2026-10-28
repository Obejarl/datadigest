# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private
reporting instead: the repository's **Security** tab → **Report a vulnerability**.
Include what you found, how to reproduce it and, if you can, what you think the impact is.

This is a personal project, so there is no guaranteed response time. Reports are
read as soon as possible, and confirmed problems are fixed in the next release.

## Supported versions

Only the latest release receives fixes.

## Things to know before deploying

DataDigest is built to be run on your own machine or inside a trusted network:

- **Authentication is optional.** Set `ACCESS_TOKEN` to require it (see the README). Without it,
  anyone who can reach the API can read, create and delete every dataset.
- **Docker Compose binds its ports to `127.0.0.1`** on purpose. Grafana's `admin/admin` login and anonymous
  viewer are demo defaults; change them before exposing anything.
- **Uploads are untrusted input.** Files are size-limited while streaming, parsed with pandas, never
  executed, and everything derived from them is HTML-escaped (report) or written with `textContent`
  (dashboard). Optimization parameters are validated against the file's own columns.
- **`LARGE_DATA_DIR` exposes a folder to everyone who can sign in.** Files in it can be registered by
  name and profiled. Names must be one plain file name that resolves to a file directly inside the
  folder (no `..`, no sub-folders, symlinks that leave it are refused) and end in `.csv`, `.tsv`, `.txt`
  or `.parquet`. Put only data you are happy to share with every user into it. The feature is off
  unless the variable is set.
- **Dependencies** are pinned, updated weekly by Dependabot, and GitHub's secret scanning and
  push protection are enabled.
