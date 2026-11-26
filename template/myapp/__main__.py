"""myapp command line.

python -m myapp serve                 # web UI on :8080 plus the scheduled sweeps
python -m myapp sweep [--no-notify]   # one sweep now
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import config, sweep
from .db import open_db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="myapp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("sweep").add_argument("--no-notify", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = config.load()
    db = open_db(s.common.db_path)

    if a.cmd == "serve":
        import uvicorn  # pylint: disable=import-outside-toplevel

        from .web import create_app  # pylint: disable=import-outside-toplevel

        app = create_app(s, db, start_scheduler=True)
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))  # nosec B104
        return 0
    run_id = sweep.run(db, s, trigger="cli", notify_on=not a.no_notify)
    row = db.one("SELECT status FROM runs WHERE id = ?", run_id)
    return 0 if row and row["status"] in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
