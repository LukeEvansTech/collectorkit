"""The app's schema. The run ledger and the seen-before store come from collectorkit."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from collectorkit import runs, seen
from collectorkit.db import DB

SCHEMA = runs.SCHEMA + seen.SCHEMA + """
CREATE TABLE IF NOT EXISTS listings (
    source TEXT NOT NULL,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    price TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (source, key)
);
"""


def migrate(c: sqlite3.Connection) -> None:
    """Columns added after the first release go here, one ``add_column`` each."""
    del c


def open_db(path: Path) -> DB:
    db = DB(path, SCHEMA, migrate)
    runs.mark_interrupted(db)
    return db
