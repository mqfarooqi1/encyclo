"""Forward-only migration runner.

Migrations are plain ``.sql`` files named ``NNNN_description.sql``, applied in
numeric order inside a transaction and recorded with a checksum. If a file that
has already been applied is later edited, the checksum mismatch is raised as an
error rather than ignored: a migration history you cannot trust is worse than
no history at all.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Raised when the migration history is inconsistent or a file fails."""


def _ledger_ddl(schema: str) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS {schema}.schema_migrations ("
        "  version    INTEGER PRIMARY KEY,"
        "  name       TEXT NOT NULL,"
        "  checksum   TEXT NOT NULL,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )


def _discover(directory: Path) -> list[tuple[int, str, Path]]:
    found: list[tuple[int, str, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"Migration file {path.name!r} does not match NNNN_name.sql")
        found.append((int(match.group(1)), match.group(2), path))
    versions = [v for v, _, _ in found]
    if len(set(versions)) != len(versions):
        raise MigrationError(f"Duplicate migration version numbers in {directory}")
    return found


def _checksum(text: str) -> str:
    # Normalise line endings so a Windows checkout does not invalidate history.
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:16]


def applied_versions(conn: sqlite3.Connection, *, schema: str = "main") -> dict[int, str]:
    conn.execute(_ledger_ddl(schema))
    rows = conn.execute(
        f"SELECT version, checksum FROM {schema}.schema_migrations ORDER BY version"
    ).fetchall()
    return {r["version"]: r["checksum"] for r in rows}


def migrate(
    conn: sqlite3.Connection, directory: Path | None = None, *, schema: str = "main"
) -> list[str]:
    """Apply every pending migration; return the names that were applied."""
    directory = directory or MIGRATIONS_DIR
    already = applied_versions(conn, schema=schema)
    applied: list[str] = []

    for version, name, path in _discover(directory):
        sql = path.read_text(encoding="utf-8")
        digest = _checksum(sql)
        if version in already:
            if already[version] != digest:
                raise MigrationError(
                    f"Migration {version:04d}_{name} was modified after being applied "
                    f"(recorded {already[version]}, file {digest}). "
                    "Add a new migration instead of editing history."
                )
            continue
        log.info("applying migration %04d_%s to schema %s", version, name, schema)
        # executescript() implicitly commits any open transaction, so the DDL and
        # the ledger row are committed as one step immediately afterwards.
        try:
            conn.executescript(sql)
        except sqlite3.Error as exc:
            conn.rollback()
            raise MigrationError(f"Migration {version:04d}_{name} failed: {exc}") from exc
        conn.execute(
            f"INSERT INTO {schema}.schema_migrations (version, name, checksum) "
            "VALUES (?, ?, ?)",
            (version, name, digest),
        )
        conn.commit()
        applied.append(f"{version:04d}_{name}")
    return applied


def migrate_all(
    conn: sqlite3.Connection, user_db: Path | None = None
) -> dict[str, list[str]]:
    """Migrate the content database, and the user database if one is given.

    The user database gets its own short-lived connection rather than being
    migrated through the ``usr`` ATTACH. ``executescript`` cannot be pointed at
    an attached schema -- unqualified ``CREATE TABLE`` always lands in ``main``
    -- so migrating through the attach would silently build the personal-data
    tables inside the content database, defeating the separation the whole
    content-pack design relies on.
    """
    result = {"content": migrate(conn, MIGRATIONS_DIR, schema="main")}
    user_dir = MIGRATIONS_DIR / "user"
    if user_db is not None and user_dir.is_dir():
        user_db.parent.mkdir(parents=True, exist_ok=True)
        user_conn = sqlite3.connect(user_db)
        user_conn.row_factory = _dict_row
        try:
            user_conn.execute("PRAGMA journal_mode = WAL")
            user_conn.execute("PRAGMA foreign_keys = ON")
            result["user"] = migrate(user_conn, user_dir, schema="main")
        finally:
            user_conn.close()
    return result


def _dict_row(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}
