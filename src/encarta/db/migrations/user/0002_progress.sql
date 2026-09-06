-- user/0002_progress: what a child has earned. Local to this device, never sent
-- anywhere, and deliberately additive so a content update cannot erase it.

CREATE TABLE earned_badge (
    badge_key TEXT PRIMARY KEY,
    earned_at TEXT NOT NULL DEFAULT (datetime('now')),
    detail    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail))
);

CREATE TABLE trail_progress (
    trail_key     TEXT NOT NULL,
    station_key   TEXT NOT NULL,
    best_score    INTEGER NOT NULL DEFAULT 0,
    total         INTEGER NOT NULL DEFAULT 0,
    stars         INTEGER NOT NULL DEFAULT 0 CHECK (stars BETWEEN 0 AND 3),
    attempts      INTEGER NOT NULL DEFAULT 0,
    completed_at  TEXT,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (trail_key, station_key)
);
CREATE INDEX idx_trailprog_trail ON trail_progress(trail_key);
