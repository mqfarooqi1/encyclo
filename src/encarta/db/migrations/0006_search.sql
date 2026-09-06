-- 0006_search: full-text index, query expansion, and an optional vector layer.
--
-- The FTS table is NOT an external-content table and is NOT trigger-maintained.
-- Indexable text is assembled across article + current revision + every reading
-- level + facts + categories, so it is rebuilt explicitly by SearchIndexer
-- whenever a revision is published. That keeps the index and the trust model
-- in step: only *published current* revisions are ever searchable.

CREATE VIRTUAL TABLE article_fts USING fts5(
    title,
    aliases,
    summary,
    body,
    facts,
    categories,
    tokenize = 'unicode61 remove_diacritics 2',
    prefix = '2 3 4'            -- powers as-you-type autocomplete
);

-- Term dictionary derived from the index; used for did-you-mean correction
-- without shipping a separate spellcheck dictionary.
CREATE VIRTUAL TABLE article_fts_vocab USING fts5vocab(article_fts, 'row');

-- Query expansion. Lets "largest dinosaur" or "T rex" reach the right article
-- without the user knowing the exact title.
CREATE TABLE synonym (
    id       INTEGER PRIMARY KEY,
    term     TEXT    NOT NULL,
    expands_to TEXT  NOT NULL,
    weight   REAL    NOT NULL DEFAULT 0.8 CHECK (weight > 0 AND weight <= 1),
    UNIQUE (term, expands_to)
);
CREATE INDEX idx_synonym_term ON synonym(term);

-- Optional semantic layer. Embeddings are stored as raw float32 BLOBs; the app
-- works fully without this table being populated (no-AI mode).
CREATE TABLE embedding (
    article_id INTEGER PRIMARY KEY REFERENCES article(id) ON DELETE CASCADE,
    model      TEXT    NOT NULL,
    dim        INTEGER NOT NULL CHECK (dim > 0),
    vector     BLOB    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Chunk-level embeddings for retrieval-augmented answering over long articles.
CREATE TABLE embedding_chunk (
    id            INTEGER PRIMARY KEY,
    article_id    INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    reading_level TEXT    NOT NULL,
    chunk_index   INTEGER NOT NULL,
    text          TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    dim           INTEGER NOT NULL CHECK (dim > 0),
    vector        BLOB    NOT NULL,
    UNIQUE (article_id, reading_level, chunk_index)
);
CREATE INDEX idx_chunk_article ON embedding_chunk(article_id);
