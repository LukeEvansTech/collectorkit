"""The run ledger: one row per sweep, one row per source it tried.

Include ``SCHEMA`` in the app's schema; add the app's own counters with ``db.add_column``.
A source that failed has ``count`` NULL and an ``error``; a source that read nothing it should
have is a failure, not a zero. ``last_success`` is what the last-success gauge reports.
"""

from __future__ import annotations

import datetime as dt

from .db import DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL,
    finished TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    trigger TEXT NOT NULL DEFAULT 'schedule',
    listings INTEGER NOT NULL DEFAULT 0,
    alerts TEXT NOT NULL DEFAULT '',
    error TEXT
);
CREATE TABLE IF NOT EXISTS run_sources (
    run_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    count INTEGER,
    error TEXT,
    seconds REAL NOT NULL DEFAULT 0,
    partial INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, name)
);
"""

FORMAT = "%Y-%m-%d %H:%M:%S"
# A sweep counts only when it read something.
DELIVERED = "status IN ('success', 'partial') AND listings > 0"


def now() -> str:
    """UTC, in the form SQLite's own date functions read."""
    return dt.datetime.now(dt.timezone.utc).strftime(FORMAT)


def parse(stamp: str) -> dt.datetime:
    return dt.datetime.strptime(stamp, FORMAT).replace(tzinfo=dt.timezone.utc)


def mark_interrupted(db: DB) -> None:
    """Call at start-up: a sweep cut off by a restart never finishes."""
    db.run("UPDATE runs SET status = 'interrupted', finished = started WHERE status = 'running'")


def start(db: DB, trigger: str = "schedule") -> int:
    return db.run("INSERT INTO runs (started, trigger) VALUES (?, ?)", now(), trigger)


def source(
    db: DB,
    run_id: int,
    name: str,
    count: int | None = None,
    error: str | None = None,
    seconds: float = 0.0,
    partial: bool = False,
) -> None:
    db.run(
        "INSERT OR REPLACE INTO run_sources (run_id, name, count, error, seconds, partial)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        run_id,
        name,
        count,
        error,
        round(seconds, 2),
        int(partial),
    )


def finish(
    db: DB,
    run_id: int,
    status: str | None = None,
    alerts: str = "",
    error: str | None = None,
) -> str:
    """Close the run and return its status.

    Unless given, the status comes from the sources: ``success`` when all read, ``partial``
    when some failed, ``failed`` when all failed or none ran. ``listings`` is their total."""
    rows = db.all("SELECT count, error FROM run_sources WHERE run_id = ?", run_id)
    read = [r for r in rows if r["error"] is None and r["count"] is not None]
    if status is None:
        if error or not read:
            status = "failed"
        else:
            status = "success" if len(read) == len(rows) else "partial"
    db.run(
        "UPDATE runs SET finished = ?, status = ?, listings = ?, alerts = ?, error = ? WHERE id = ?",
        now(),
        status,
        sum(r["count"] for r in read),
        alerts,
        error,
        run_id,
    )
    return status


def coverage(db: DB, run_id: int) -> list[str]:
    """One line per source for a mail's footer: what was read and what failed."""
    out = []
    for r in db.all("SELECT * FROM run_sources WHERE run_id = ? ORDER BY name", run_id):
        if r["error"] is not None or r["count"] is None:
            out.append(f"{r['name']}: FAILED ({r['error'] or 'no result'})")
        else:
            cut = ", cut short" if r["partial"] else ""
            out.append(f"{r['name']}: ok, {r['count']} listings{cut}")
    return out


def last_success(db: DB, where: str = DELIVERED) -> float:
    """Unix time the last delivering run finished, or 0. ``where`` is the app's own definition
    of delivering, a fixed SQL condition on ``runs`` (never user input)."""
    row = db.one(
        f"SELECT finished FROM runs WHERE finished IS NOT NULL AND {where}"  # nosec B608
        " ORDER BY finished DESC LIMIT 1"
    )
    return parse(row["finished"]).timestamp() if row else 0.0
