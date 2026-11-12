"""Start DataDigest with one command: bring the database up to date, then serve the dashboard.

    python -m datadigest                 # http://127.0.0.1:8000, SQLite file in this folder
    python -m datadigest --port 9000

Nothing else is needed for this: no Docker, no Redis, no PostgreSQL. Uploads are profiled by
the API process itself (inline mode). The Compose and Kubernetes setups add the queue, the
workers and PostgreSQL when one process is no longer enough.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")


def main(argv: list[str] | None = None, serve=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m datadigest", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--host", default="127.0.0.1", help="0.0.0.0 to accept connections from other machines"
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    migrate()
    if serve is None:
        import uvicorn

        serve = uvicorn.run
    print(f"DataDigest is starting on http://{args.host}:{args.port}")
    serve("datadigest.api.main:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
