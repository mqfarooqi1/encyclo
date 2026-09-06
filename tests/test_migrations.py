"""Schema and migration behaviour."""

from __future__ import annotations

import pytest

from encarta.db import connect
from encarta.db.migrate import MigrationError, migrate, migrate_all


def _tables(conn, schema="main"):
    return {
        r["name"]
        for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"
        ).fetchall()
    }


def test_migrations_create_the_expected_tables(empty_conn):
    tables = _tables(empty_conn)
    for expected in (
        "article", "article_revision", "article_content", "fact", "fact_citation",
        "source", "citation", "media", "relation", "timeline_event", "place",
        "quiz", "learning_path", "update_proposal", "issue", "audit_log", "article_fts",
    ):
        assert expected in tables, f"{expected} missing from content schema"


def test_migrations_are_idempotent(empty_conn, tmp_path):
    assert migrate_all(empty_conn, tmp_path / "u.db") == {"content": [], "user": []}


def test_user_data_lives_in_a_separate_database(tmp_path):
    """Content packs must be replaceable without touching personal data."""
    content_db, user_db = tmp_path / "c.db", tmp_path / "u.db"
    conn = connect(content_db, user_db)
    migrate_all(conn, user_db)

    content_tables = _tables(conn, "main")
    user_tables = _tables(conn, "usr")

    assert "bookmark" in user_tables
    assert "bookmark" not in content_tables, "personal data leaked into the content database"
    assert "article" in content_tables
    assert "article" not in user_tables
    conn.close()


def test_editing_an_applied_migration_is_rejected(tmp_path):
    """A migration history that can be silently rewritten is worthless."""
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / "0001_thing.sql").write_text("CREATE TABLE thing (id INTEGER);", encoding="utf-8")

    conn = connect(tmp_path / "db.sqlite")
    assert migrate(conn, migrations) == ["0001_thing"]

    (migrations / "0001_thing.sql").write_text(
        "CREATE TABLE thing (id INTEGER, extra TEXT);", encoding="utf-8"
    )
    with pytest.raises(MigrationError, match="modified after being applied"):
        migrate(conn, migrations)
    conn.close()


def test_badly_named_migration_is_rejected(tmp_path):
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / "oops.sql").write_text("SELECT 1;", encoding="utf-8")
    conn = connect(tmp_path / "db.sqlite")
    with pytest.raises(MigrationError, match="does not match"):
        migrate(conn, migrations)
    conn.close()


def test_foreign_keys_are_enforced(empty_conn):
    """ON DELETE CASCADE is inert unless foreign_keys is on per connection."""
    assert empty_conn.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"] == 1


def test_ai_revision_cannot_be_published_without_a_reviewer(empty_conn):
    empty_conn.execute(
        "INSERT INTO article_type (key, label) VALUES ('t', 'T')"
    )
    empty_conn.execute(
        "INSERT INTO article (slug, title, type_id) VALUES ('a', 'A', 1)"
    )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        empty_conn.execute(
            "INSERT INTO article_revision (article_id, origin, created_by) "
            "VALUES (1, 'ai_approved', 'model')"
        )
