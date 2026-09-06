-- 0005_userdata: personalisation. Stored in a SEPARATE database file from content
-- (see db/connection.py ATTACH), so content packs can be replaced or upgraded
-- without ever touching the user's bookmarks, notes or progress.

CREATE TABLE setting (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE bookmark (
    id          INTEGER PRIMARY KEY,
    article_slug TEXT   NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    note        TEXT
);

CREATE TABLE collection (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    icon       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE collection_item (
    collection_id INTEGER NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
    article_slug  TEXT    NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (collection_id, article_slug)
);

CREATE TABLE note (
    id           INTEGER PRIMARY KEY,
    article_slug TEXT    NOT NULL,
    body         TEXT    NOT NULL,
    anchor_quote TEXT,           -- highlighted passage this note attaches to
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_note_article ON note(article_slug);

CREATE TABLE reading_progress (
    article_slug  TEXT PRIMARY KEY,
    reading_level TEXT NOT NULL DEFAULT 'adult',
    scroll_pct    REAL NOT NULL DEFAULT 0 CHECK (scroll_pct BETWEEN 0 AND 1),
    is_learned    INTEGER NOT NULL DEFAULT 0 CHECK (is_learned IN (0, 1)),
    last_read_at  TEXT NOT NULL DEFAULT (datetime('now')),
    read_count    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_progress_recent ON reading_progress(last_read_at DESC);

CREATE TABLE quiz_attempt (
    id           INTEGER PRIMARY KEY,
    quiz_key     TEXT    NOT NULL,
    score        INTEGER NOT NULL,
    total        INTEGER NOT NULL,
    completed_at TEXT    NOT NULL DEFAULT (datetime('now')),
    detail       TEXT    CHECK (detail IS NULL OR json_valid(detail))
);
CREATE INDEX idx_attempt_quiz ON quiz_attempt(quiz_key, completed_at DESC);

CREATE TABLE path_progress (
    path_key     TEXT PRIMARY KEY,
    step_index   INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
