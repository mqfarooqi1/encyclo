-- 0003_graph: the knowledge graph, the deep-time timeline, and geography.

CREATE TABLE relation (
    id              INTEGER PRIMARY KEY,
    from_article_id INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    to_article_id   INTEGER NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    kind            TEXT    NOT NULL
                      CHECK (kind IN ('part_of','member_of','lived_during','located_in','discovered_by',
                                      'studied_by','preceded_by','succeeded_by','causes','contrasts_with',
                                      'example_of','related')),
    weight          REAL    NOT NULL DEFAULT 1.0 CHECK (weight > 0),
    note            TEXT,
    UNIQUE (from_article_id, to_article_id, kind),
    CHECK (from_article_id <> to_article_id)
);
CREATE INDEX idx_relation_from ON relation(from_article_id, kind);
CREATE INDEX idx_relation_to   ON relation(to_article_id, kind);

-- Years are signed reals so a single axis spans 4.54 billion years ago to today.
-- -4540000000 = formation of Earth; 1969 = Apollo 11. Precision is explicit.
CREATE TABLE timeline_event (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER REFERENCES article(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    start_year  REAL    NOT NULL,
    end_year    REAL,
    precision   TEXT    NOT NULL DEFAULT 'exact'
                  CHECK (precision IN ('exact','year','decade','century','millennium','million_years','estimate')),
    era         TEXT,
    category_id INTEGER REFERENCES category(id) ON DELETE SET NULL,
    importance  INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    epistemic   TEXT    NOT NULL DEFAULT 'fact'
                  CHECK (epistemic IN ('fact','estimate','interpretation','uncertain','contested')),
    CHECK (end_year IS NULL OR end_year >= start_year)
);
CREATE INDEX idx_timeline_span ON timeline_event(start_year, end_year);
CREATE INDEX idx_timeline_imp  ON timeline_event(importance DESC, start_year);

CREATE TABLE place (
    id           INTEGER PRIMARY KEY,
    article_id   INTEGER REFERENCES article(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    kind         TEXT    NOT NULL DEFAULT 'point'
                   CHECK (kind IN ('point','country','region','city','site','fossil_site','habitat','route','empire')),
    lat          REAL,
    lon          REAL,
    country_code TEXT,
    -- Geometry as GeoJSON text; the licence of the underlying dataset is recorded.
    geojson      TEXT,
    dataset_uid  TEXT,
    from_year    REAL,
    to_year      REAL,
    CHECK (lat IS NULL OR (lat BETWEEN -90 AND 90)),
    CHECK (lon IS NULL OR (lon BETWEEN -180 AND 180)),
    CHECK (geojson IS NULL OR json_valid(geojson))
);
CREATE INDEX idx_place_article ON place(article_id);
CREATE INDEX idx_place_country ON place(country_code);

-- R-Tree spatial index for map viewport and proximity queries.
CREATE VIRTUAL TABLE place_bbox USING rtree(id, min_lat, max_lat, min_lon, max_lon);
