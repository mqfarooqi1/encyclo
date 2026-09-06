-- 0007_trails: the Explorer Trail — quizzing as a journey rather than a form.
--
-- A trail is an ordered set of stations. Each station draws its questions from a
-- quiz and awards a badge. Trails are content, not code: adding one is a JSON
-- edit, and the game board renders whatever the data describes.

CREATE TABLE badge (
    id          INTEGER PRIMARY KEY,
    key         TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    icon        TEXT    NOT NULL DEFAULT '★',
    -- How it is earned, so the UI can explain it before it is awarded rather
    -- than surprising the child with an unexplained reward.
    criteria    TEXT    NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE trail (
    id                  INTEGER PRIMARY KEY,
    key                 TEXT    NOT NULL UNIQUE,
    title               TEXT    NOT NULL,
    description         TEXT    NOT NULL DEFAULT '',
    icon                TEXT,
    age_band            TEXT    NOT NULL DEFAULT 'age9_12'
                          CHECK (age_band IN ('age6_8','age9_12','teen','adult')),
    -- Awarded for clearing every station. Data, so adding a trail needs no code.
    completion_badge_id INTEGER REFERENCES badge(id) ON DELETE SET NULL,
    sort_order          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE trail_station (
    id          INTEGER PRIMARY KEY,
    trail_id    INTEGER NOT NULL REFERENCES trail(id) ON DELETE CASCADE,
    sort_order  INTEGER NOT NULL,
    key         TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    subtitle    TEXT    NOT NULL DEFAULT '',
    icon        TEXT    NOT NULL DEFAULT '📍',
    -- Palette hint for the board. Kept as a name, not a hex value, so the
    -- theme decides the actual colour in light and dark mode.
    palette     TEXT    NOT NULL DEFAULT 'teal'
                  CHECK (palette IN ('teal','amber','rose','violet','green','blue')),
    quiz_id     INTEGER REFERENCES quiz(id) ON DELETE SET NULL,
    badge_id    INTEGER REFERENCES badge(id) ON DELETE SET NULL,
    article_id  INTEGER REFERENCES article(id) ON DELETE SET NULL,
    UNIQUE (trail_id, sort_order),
    UNIQUE (trail_id, key)
);
CREATE INDEX idx_station_trail ON trail_station(trail_id, sort_order);
