"""SQLite storage. One connection per unit of work; WAL lets the web UI read while a sweep writes.

The app owns its schema: pass the ``CREATE TABLE IF NOT EXISTS`` script and, for columns added
after a release, a ``migrate(connection)`` function that calls ``add_column``. The ``kv`` table
(JSON values by key) is always there.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

KV = "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);\n"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def columns(c: sqlite3.Connection, table: str) -> set[str]:
    if not _NAME.fullmatch(table):
        raise ValueError(f"not a table name: {table!r}")
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}


def add_column(c: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """Add ``column`` to ``table`` unless it is there; True when it was added.

    ``ddl`` is the type and constraints, e.g. ``"INTEGER NOT NULL DEFAULT 0"``."""
    if not _NAME.fullmatch(column):
        raise ValueError(f"not a column name: {column!r}")
    if column in columns(c, table):
        return False
    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    return True


class DB:
    def __init__(
        self,
        path: Path | str,
        schema: str = "",
        migrate: Callable[[sqlite3.Connection], None] | None = None,
    ):
        self.path = Path(path)
        with self.tx() as c:
            c.executescript(KV + schema)
            if migrate:
                migrate(c)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def all(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        with self.tx() as c:
            return c.execute(sql, args).fetchall()

    def one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        with self.tx() as c:
            return c.execute(sql, args).fetchone()

    def run(self, sql: str, *args: Any) -> int:
        with self.tx() as c:
            cur = c.execute(sql, args)
            return int(cur.lastrowid or 0)

    def get(self, key: str, default: Any) -> Any:
        row = self.one("SELECT value FROM kv WHERE key = ?", key)
        return json.loads(row["value"]) if row else default

    def put(self, key: str, value: Any) -> None:
        self.run(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            key,
            json.dumps(value),
        )
