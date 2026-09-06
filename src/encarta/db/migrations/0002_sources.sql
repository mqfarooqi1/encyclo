-- 0002_sources: the evidence layer. Sources are first-class records with a
-- reliability tier and an explicit verification state. A source is NEVER assumed
-- live or correct just because a URL was written down.

CREATE TABLE source (
    id                  INTEGER PRIMARY KEY,
    uid                 TEXT    NOT NULL UNIQUE,   -- stable key, e.g. "nasa-mars-facts"
    title               TEXT    NOT NULL,
    publisher           TEXT    NOT NULL,
    authors             TEXT,
    source_type         TEXT    NOT NULL DEFAULT 'web'
                          CHECK (source_type IN ('journal','book','government','museum','university',
                                                 'organisation','encyclopaedia','dataset','web','news')),
    url                 TEXT,
    doi                 TEXT,
    isbn                TEXT,
    published_date      TEXT,
    accessed_date       TEXT,
    -- Tier 1 authoritative .. Tier 4 general. See docs/SOURCE_POLICY.md.
    tier                INTEGER NOT NULL DEFAULT 4 CHECK (tier BETWEEN 1 AND 4),
    license             TEXT,
    license_url         TEXT,
    -- Verification is earned, not assumed. New sources start unverified and are
    -- only promoted by the link checker, which requires network access.
    verification_status TEXT    NOT NULL DEFAULT 'unverified'
                          CHECK (verification_status IN ('unverified','verified','broken','moved','paywalled')),
    last_checked_at     TEXT,
    http_status         INTEGER,
    notes               TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_source_tier   ON source(tier);
CREATE INDEX idx_source_verify ON source(verification_status);
CREATE UNIQUE INDEX idx_source_doi ON source(doi) WHERE doi IS NOT NULL;

-- A citation binds ONE claim to ONE source. Citations hang off a revision, so
-- rolling an article back also rolls back exactly the evidence that supported it.
CREATE TABLE citation (
    id          INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES article_revision(id) ON DELETE CASCADE,
    source_id   INTEGER NOT NULL REFERENCES source(id) ON DELETE RESTRICT,
    marker      INTEGER NOT NULL,          -- the [1] rendered in the body
    claim       TEXT    NOT NULL,          -- what this source is asked to support
    locator     TEXT,                      -- page / section / table
    quote       TEXT,
    -- Honest about how well the source supports the claim.
    supports    TEXT    NOT NULL DEFAULT 'supports'
                  CHECK (supports IN ('supports','partially','background','contradicts')),
    UNIQUE (revision_id, marker)
);
CREATE INDEX idx_citation_source ON citation(source_id);

-- Which citations support which quick-facts. Many-to-many, because one source
-- routinely establishes several facts at once (a NASA planet page supplies
-- diameter, mass and orbital period together), and one fact may need more than
-- one source. Modelling this as a column on citation would force authors to
-- duplicate a citation per fact, which is how citation lists become dishonest.
CREATE TABLE fact_citation (
    fact_id     INTEGER NOT NULL REFERENCES fact(id) ON DELETE CASCADE,
    citation_id INTEGER NOT NULL REFERENCES citation(id) ON DELETE CASCADE,
    PRIMARY KEY (fact_id, citation_id)
);
CREATE INDEX idx_factcite_citation ON fact_citation(citation_id);

-- Every media item carries its licence with it. Media with is_redistributable = 0
-- is referenced by URL only and is never bundled into an offline content pack.
CREATE TABLE media (
    id                 INTEGER PRIMARY KEY,
    uid                TEXT    NOT NULL UNIQUE,
    kind               TEXT    NOT NULL
                         CHECK (kind IN ('image','diagram','audio','video','map','animation','model3d')),
    title              TEXT    NOT NULL,
    description        TEXT,
    creator            TEXT,
    credit_line        TEXT    NOT NULL,
    license            TEXT    NOT NULL,
    license_url        TEXT,
    source_url         TEXT,
    accessed_date      TEXT,
    provenance         TEXT    NOT NULL
                         CHECK (provenance IN ('public_domain','creative_commons','government',
                                               'owned','third_party','ai_generated')),
    is_redistributable INTEGER NOT NULL DEFAULT 0 CHECK (is_redistributable IN (0, 1)),
    local_path         TEXT,
    sha256             TEXT,
    bytes              INTEGER,
    mime               TEXT,
    width              INTEGER,
    height             INTEGER,
    duration_s         REAL,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Anything bundled offline must have a local file and a checksum.
    CHECK (is_redistributable = 0 OR (local_path IS NOT NULL AND sha256 IS NOT NULL))
);
CREATE INDEX idx_media_kind ON media(kind);

CREATE TABLE article_media (
    article_id INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    media_id   INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL DEFAULT 'inline'
                 CHECK (role IN ('hero','inline','gallery','diagram','map','pronunciation')),
    caption    TEXT,
    alt_text   TEXT    NOT NULL DEFAULT '',   -- accessibility is not optional
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (article_id, media_id, role)
);
CREATE INDEX idx_artmedia_media ON article_media(media_id);
