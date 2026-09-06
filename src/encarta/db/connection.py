"""SQLite connection management.

Two physical databases, deliberately:

  content  -- articles, sources, media, search index. Replaceable. Shipped in
              content packs. Read-mostly while the app is running.
  user     -- bookmarks, notes, progress. Never shipped, never overwritten by an
              update, and attached to the same connection so one query can join
              "articles I bookmarked" without a second round trip.

The user database is ATTACHed as schema ``usr``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Applied to every connection. WAL keeps reads fast while the update pipeline
# writes. foreign_keys is OFF by default in SQLite and must be enabled per
# connection, or every ON DELETE CASCADE in the schema is silently inert.
_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA temp_store = MEMORY",
    "PRAGMA cache_size = -16000",  # negative means KiB, so ~16 MB
)


def _row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def connect(
    content_db: Path, user_db: Path | None = None, *, read_only: bool = False
) -> sqlite3.Connection:
    """Open a configured connection, optionally attaching the user database."""
    content_db.parent.mkdir(parents=True, exist_ok=True)
    if read_only and content_db.exists():
        conn = sqlite3.connect(
            f"file:{content_db.as_posix()}?mode=ro", uri=True, check_same_thread=False
        )
    else:
        conn = sqlite3.connect(content_db, check_same_thread=False)
    conn.row_factory = _row_factory
    for pragma in _PRAGMAS:
        try:
            conn.execute(pragma)
        except sqlite3.DatabaseError:  # read-only connections reject some pragmas
            log.debug("pragma refused: %s", pragma)
    if user_db is not None:
        user_db.parent.mkdir(parents=True, exist_ok=True)
        conn.execute("ATTACH DATABASE ? AS usr", (str(user_db),))
        conn.execute("PRAGMA usr.journal_mode = WAL")
    return conn


class Database:
    """Thread-local connection holder.

    The WSGI server is threaded and SQLite connections are not safely shared
    across threads, so each thread lazily gets its own.
    """

    def __init__(self, content_db: Path, user_db: Path | None = None) -> None:
        self.content_db = content_db
        self.user_db = user_db
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        existing: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if existing is None:
            existing = connect(self.content_db, self.user_db)
            self._local.conn = existing
        return existing

    def query(self, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Any = ()) -> dict[str, Any] | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Any = ()) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        return next(iter(row.values())) if row else None

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows: Any) -> sqlite3.Cursor:
        return self.conn.executemany(sql, rows)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Atomic unit of work; rolls back on any exception."""
        conn = self.conn
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()

    def close(self) -> None:
        existing: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if existing is not None:
            existing.close()
            self._local.conn = None
