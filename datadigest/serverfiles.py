"""Files that already live on the server (LARGE_DATA_DIR), for data too big to upload.

Uploads are capped at MAX_UPLOAD_MB because they are stored in the database. A bigger file is
dropped into LARGE_DATA_DIR by whoever runs the server (a mounted volume, an `scp`, a data
pipeline) and registered by name; the worker then reads it from disk, with Spark if it is large.

The name in the URL is never trusted: it must be one plain file name that resolves to a file
directly inside that directory, so `../etc/passwd` and symlinks pointing elsewhere are refused.
"""

from __future__ import annotations

from pathlib import Path

from datadigest.config import Settings

SUFFIXES = (".csv", ".tsv", ".txt", ".parquet")
MAX_LISTED = 200


class ServerFileError(Exception):
    """The file is not available. The message is safe to show to users."""


def root(settings: Settings) -> Path | None:
    return Path(settings.large_data_dir).resolve() if settings.large_data_dir else None


def _usable(path: Path) -> bool:
    # A Parquet dataset written by Spark or pyarrow is a folder of part files.
    return path.is_file() or (path.is_dir() and path.suffix.lower() == ".parquet")


def resolve(name: str, settings: Settings) -> Path:
    base = root(settings)
    if base is None:
        raise ServerFileError("Server-side files are not enabled (set LARGE_DATA_DIR)")
    if not name or name != Path(name).name or name.startswith(".") or not name.lower().endswith(SUFFIXES):
        raise ServerFileError("Unknown file")
    path = (base / name).resolve()  # follows symlinks, so a link out of the directory fails the check below
    if path.parent != base or not _usable(path):
        raise ServerFileError("Unknown file")
    return path


def size_of(path: Path) -> int:
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return path.stat().st_size


def list_files(settings: Settings) -> list[tuple[str, int]]:
    """(name, size in bytes) of the files that can be registered, in name order."""
    base = root(settings)
    if base is None or not base.is_dir():
        return []
    found = []
    for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        try:
            found.append((entry.name, size_of(resolve(entry.name, settings))))
        except (ServerFileError, OSError):
            continue
        if len(found) >= MAX_LISTED:
            break
    return found
