"""Shared fixtures.

Every test runs against a temporary database built from the real content pack,
so the suite exercises the same migrations, loader and validator that ship.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from encarta.config import Config, project_root
from encarta.content.loader import PackLoader
from encarta.db import connect
from encarta.db.migrate import migrate_all
from encarta.services import QualityService, SearchIndexer

PACK = project_root() / "content" / "packs" / "core"


@pytest.fixture(scope="session")
def pack_dir() -> Path:
    assert PACK.is_dir(), f"core content pack missing at {PACK}"
    return PACK


@pytest.fixture(scope="session")
def loaded_db(tmp_path_factory, pack_dir) -> Path:
    """Build the full database once per session; tests open their own connections."""
    data = tmp_path_factory.mktemp("encarta-data")
    content_db, user_db = data / "content.db", data / "user.db"
    conn = connect(content_db, user_db)
    migrate_all(conn, user_db)
    PackLoader(conn).load_pack(pack_dir)
    SearchIndexer(conn).rebuild()
    QualityService(conn).score_all()
    conn.close()
    return data


@pytest.fixture
def conn(loaded_db) -> sqlite3.Connection:
    connection = connect(loaded_db / "content.db", loaded_db / "user.db")
    yield connection
    connection.close()


@pytest.fixture
def empty_conn(tmp_path) -> sqlite3.Connection:
    """A migrated but empty database, for loader and migration tests."""
    content_db, user_db = tmp_path / "c.db", tmp_path / "u.db"
    connection = connect(content_db, user_db)
    migrate_all(connection, user_db)
    yield connection
    connection.close()


@pytest.fixture
def config(loaded_db) -> Config:
    return Config(data_dir=loaded_db, content_dir=project_root() / "content")
