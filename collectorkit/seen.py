"""Which listings of a source have been seen before.

A source's first read is a baseline: everything on it is recorded and nothing is new, so adding
a shop does not announce its whole catalogue. Call ``fresh`` when a source has been read and
``commit`` only once the message carrying the new ones has been sent: a failed send leaves them
new for the next run.
"""

from __future__ import annotations

from typing import Iterable

from .db import DB
from .runs import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    source TEXT NOT NULL,
    key TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (source, key)
);
CREATE TABLE IF NOT EXISTS seen_sources (source TEXT PRIMARY KEY, baselined TEXT NOT NULL);
"""


def baselined(db: DB, source: str) -> bool:
    return db.one("SELECT 1 FROM seen_sources WHERE source = ?", source) is not None


def fresh(db: DB, source: str, keys: Iterable[str]) -> list[str]:
    """The keys not seen before, in the order given; none while the source has no baseline."""
    if not baselined(db, source):
        return []
    known = {r["key"] for r in db.all("SELECT key FROM seen WHERE source = ?", source)}
    out: list[str] = []
    for k in keys:
        if k not in known:
            known.add(k)
            out.append(k)
    return out


def commit(db: DB, source: str, keys: Iterable[str]) -> None:
    """Record the keys as seen and the source as baselined."""
    stamp = now()
    with db.tx() as c:
        c.executemany(
            "INSERT OR IGNORE INTO seen (source, key, first_seen) VALUES (?, ?, ?)",
            [(source, k, stamp) for k in keys],
        )
        c.execute(
            "INSERT OR IGNORE INTO seen_sources (source, baselined) VALUES (?, ?)", (source, stamp)
        )
