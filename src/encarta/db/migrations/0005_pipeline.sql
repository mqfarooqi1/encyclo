-- 0005_pipeline: the update, review and quality machinery.
-- Nothing in here can change an article by itself. Proposals are inert records
-- until a named reviewer approves them; approval is what creates a revision.

-- Per-category / per-type review cadence (requirement: update frequency varies).
CREATE TABLE review_policy (
    id             INTEGER PRIMARY KEY,
    scope          TEXT    NOT NULL CHECK (scope IN ('type','category','article')),
    scope_key      TEXT    NOT NULL,
    review_months  INTEGER NOT NULL CHECK (review_months > 0),
    rationale      TEXT    NOT NULL DEFAULT '',
    UNIQUE (scope, scope_key)
);

-- An AI- or importer-generated proposal to change an article.
CREATE TABLE update_proposal (
    id             INTEGER PRIMARY KEY,
    article_id     INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    status         TEXT    NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected','superseded','applied')),
    origin         TEXT    NOT NULL
                     CHECK (origin IN ('ai','importer','human','link_check','fact_check')),
    ai_model       TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Structured field-level diff: [{field, path, before, after, rationale}]
    diff_json      TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(diff_json)),
    rationale      TEXT    NOT NULL DEFAULT '',
    confidence     REAL    CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
    reviewer       TEXT,
    reviewed_at    TEXT,
    review_note    TEXT,
    applied_revision_id INTEGER REFERENCES article_revision(id) ON DELETE SET NULL,
    -- A proposal cannot leave 'pending' without a named human reviewer.
    CHECK (status = 'pending' OR status = 'superseded' OR reviewer IS NOT NULL)
);
CREATE INDEX idx_proposal_status  ON update_proposal(status, created_at DESC);
CREATE INDEX idx_proposal_article ON update_proposal(article_id, status);

-- Every proposal must be backed by the sources it was derived from.
CREATE TABLE proposal_source (
    proposal_id INTEGER NOT NULL REFERENCES update_proposal(id) ON DELETE CASCADE,
    source_id   INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    excerpt     TEXT,
    PRIMARY KEY (proposal_id, source_id)
);

-- Fact-check and integrity findings. These FLAG, they never auto-correct.
CREATE TABLE issue (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER REFERENCES article(id) ON DELETE CASCADE,
    source_id   INTEGER REFERENCES source(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL
                  CHECK (kind IN ('missing_citation','broken_source','unsupported_claim','outdated',
                                  'contradiction','duplicate_article','suspicious_statistic',
                                  'inconsistent_unit','inconsistent_name','orphan_relation',
                                  'missing_reading_level','missing_alt_text','low_quality')),
    severity    TEXT    NOT NULL DEFAULT 'warning'
                  CHECK (severity IN ('info','warning','error')),
    detail      TEXT    NOT NULL DEFAULT '',
    detected_at TEXT    NOT NULL DEFAULT (datetime('now')),
    status      TEXT    NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open','acknowledged','resolved','wontfix')),
    resolved_at TEXT
);
CREATE INDEX idx_issue_open    ON issue(status, severity, detected_at DESC);
CREATE INDEX idx_issue_article ON issue(article_id, status);

-- Component breakdown behind article.quality_score.
CREATE TABLE quality_report (
    article_id        INTEGER PRIMARY KEY REFERENCES article(id) ON DELETE CASCADE,
    total             INTEGER NOT NULL,
    source_coverage   INTEGER NOT NULL DEFAULT 0,
    source_quality    INTEGER NOT NULL DEFAULT 0,
    freshness         INTEGER NOT NULL DEFAULT 0,
    completeness      INTEGER NOT NULL DEFAULT 0,
    readability       INTEGER NOT NULL DEFAULT 0,
    reading_levels    INTEGER NOT NULL DEFAULT 0,
    citation_coverage INTEGER NOT NULL DEFAULT 0,
    media             INTEGER NOT NULL DEFAULT 0,
    computed_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    detail_json       TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json))
);

-- Installed offline content packages.
CREATE TABLE content_pack (
    id            INTEGER PRIMARY KEY,
    key           TEXT    NOT NULL,
    version       TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    article_count INTEGER NOT NULL DEFAULT 0,
    media_bytes   INTEGER NOT NULL DEFAULT 0,
    checksum      TEXT,
    installed_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (key, version)
);

CREATE TABLE pack_article (
    pack_id    INTEGER NOT NULL REFERENCES content_pack(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    PRIMARY KEY (pack_id, article_id)
);

-- Append-only audit log. Every mutation of trusted content lands here.
CREATE TABLE audit_log (
    id         INTEGER PRIMARY KEY,
    at         TEXT    NOT NULL DEFAULT (datetime('now')),
    actor      TEXT    NOT NULL DEFAULT 'system',
    action     TEXT    NOT NULL,
    entity     TEXT    NOT NULL,
    entity_id  TEXT,
    detail     TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(detail))
);
CREATE INDEX idx_audit_entity ON audit_log(entity, entity_id, at DESC);
CREATE INDEX idx_audit_time   ON audit_log(at DESC);
