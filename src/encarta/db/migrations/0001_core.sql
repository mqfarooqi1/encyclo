-- 0001_core: article types, categories, articles, immutable revisions,
-- per-reading-level content, and structured facts with epistemic status.

CREATE TABLE article_type (
    id                   INTEGER PRIMARY KEY,
    key                  TEXT    NOT NULL UNIQUE,
    label                TEXT    NOT NULL,
    icon                 TEXT,
    -- JSON description of the quick-facts this type expects. New types can be
    -- added at any time without a schema migration; this is the extension point.
    fact_schema          TEXT    NOT NULL DEFAULT '[]',
    -- Category-specific review cadence (requirement: freshness policy per type).
    default_review_months INTEGER NOT NULL DEFAULT 36,
    CHECK (json_valid(fact_schema)),
    CHECK (default_review_months > 0)
);

CREATE TABLE category (
    id          INTEGER PRIMARY KEY,
    key         TEXT    NOT NULL UNIQUE,
    label       TEXT    NOT NULL,
    icon        TEXT,
    description TEXT,
    parent_id   INTEGER REFERENCES category(id) ON DELETE SET NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    kids_safe   INTEGER NOT NULL DEFAULT 1 CHECK (kids_safe IN (0, 1))
);
CREATE INDEX idx_category_parent ON category(parent_id, sort_order);

CREATE TABLE article (
    id                  INTEGER PRIMARY KEY,
    slug                TEXT    NOT NULL UNIQUE,
    title               TEXT    NOT NULL,
    type_id             INTEGER NOT NULL REFERENCES article_type(id),
    -- Denormalised from the current revision for fast list/search rendering.
    summary             TEXT    NOT NULL DEFAULT '',
    status              TEXT    NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft','review','published','archived')),
    current_revision_id INTEGER,
    pronunciation_ipa   TEXT,
    -- Lowest reading level for which this article has content; drives Kids Mode.
    min_reading_level   TEXT,
    kids_safe           INTEGER NOT NULL DEFAULT 1 CHECK (kids_safe IN (0, 1)),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    last_reviewed_at    TEXT,
    next_review_at      TEXT,
    quality_score       INTEGER,
    view_count          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_article_status  ON article(status, title);
CREATE INDEX idx_article_type    ON article(type_id);
CREATE INDEX idx_article_review  ON article(next_review_at) WHERE status = 'published';
CREATE INDEX idx_article_quality ON article(quality_score);

CREATE TABLE article_alias (
    article_id INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    alias      TEXT    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'alternative'
                 CHECK (kind IN ('alternative','scientific','former','abbreviation','misspelling','native')),
    PRIMARY KEY (article_id, alias)
);
CREATE INDEX idx_alias_lookup ON article_alias(alias);

CREATE TABLE article_category (
    article_id  INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
    is_primary  INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    PRIMARY KEY (article_id, category_id)
);
CREATE INDEX idx_artcat_category ON article_category(category_id);
CREATE UNIQUE INDEX idx_artcat_one_primary ON article_category(article_id) WHERE is_primary = 1;

-- Revisions are append-only. Nothing ever edits a published revision in place;
-- an update creates a new row and repoints article.current_revision_id.
CREATE TABLE article_revision (
    id                 INTEGER PRIMARY KEY,
    article_id         INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    version_major      INTEGER NOT NULL DEFAULT 1,
    version_minor      INTEGER NOT NULL DEFAULT 0,
    parent_revision_id INTEGER REFERENCES article_revision(id),
    -- Provenance is mandatory: we always know where a revision came from.
    origin             TEXT    NOT NULL
                         CHECK (origin IN ('human','import','ai_proposal','ai_approved','rollback')),
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    created_by         TEXT    NOT NULL DEFAULT 'system',
    change_reason      TEXT    NOT NULL DEFAULT '',
    change_summary     TEXT    NOT NULL DEFAULT '',
    ai_model           TEXT,
    reviewed_by        TEXT,
    reviewed_at        TEXT,
    content_hash       TEXT,
    UNIQUE (article_id, version_major, version_minor),
    -- An AI-authored revision may never be published without a named reviewer.
    CHECK (origin <> 'ai_approved' OR reviewed_by IS NOT NULL)
);
CREATE INDEX idx_revision_article ON article_revision(article_id, version_major DESC, version_minor DESC);

-- One row per (revision, reading level). Each level is authored independently;
-- a level is genuinely rewritten for its audience, not a truncation of the adult text.
CREATE TABLE article_content (
    id                INTEGER PRIMARY KEY,
    revision_id       INTEGER NOT NULL REFERENCES article_revision(id) ON DELETE CASCADE,
    reading_level     TEXT    NOT NULL
                        CHECK (reading_level IN ('age6_8','age9_12','teen','adult')),
    summary           TEXT    NOT NULL DEFAULT '',
    body_md           TEXT    NOT NULL DEFAULT '',
    reading_time_min  INTEGER NOT NULL DEFAULT 1,
    readability_grade REAL,
    word_count        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (revision_id, reading_level)
);

-- Structured quick-facts. `epistemic` is the core trust primitive: the UI renders
-- an estimate or a contested claim differently from an established fact.
CREATE TABLE fact (
    id          INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES article_revision(id) ON DELETE CASCADE,
    key         TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    value_text  TEXT    NOT NULL DEFAULT '',
    value_num   REAL,
    unit        TEXT,
    epistemic   TEXT    NOT NULL DEFAULT 'fact'
                  CHECK (epistemic IN ('fact','estimate','interpretation','opinion','uncertain','contested')),
    confidence  REAL    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    group_label TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    -- Comparable facts (size, mass, population) power Comparison Mode.
    comparable_key TEXT,
    UNIQUE (revision_id, key)
);
CREATE INDEX idx_fact_revision   ON fact(revision_id, sort_order);
CREATE INDEX idx_fact_comparable ON fact(comparable_key) WHERE comparable_key IS NOT NULL;
