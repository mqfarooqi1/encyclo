"""Trail progress and badges.

The only service that writes to the user database. Everything it stores is
local to the device and is never sent anywhere.

Design note on rewards: badges are earned for *finishing* a station, not for
streaks, speed or daily returns. There is deliberately no mechanic that rewards
coming back tomorrow — the brief asks for an educational product, not an
engagement loop, and a child who has learned the material has no reason to be
pulled back by the software.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

# A station is "cleared" at half marks; stars reward doing better than that.
PASS_RATIO = 0.5

# Distinct stations attempted before the breadth badge is awarded.
CURIOUS_STATIONS = 3


def stars_for(score: int, total: int) -> int:
    if total <= 0:
        return 0
    ratio = score / total
    if ratio >= 1.0:
        return 3
    if ratio >= 0.75:
        return 2
    if ratio >= PASS_RATIO:
        return 1
    return 0


class TrailService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- reads ---------------------------------------------------------------

    def list_trails(self, kids_only: bool = False) -> list[dict[str, Any]]:
        bands = ("age6_8", "age9_12") if kids_only else ("age6_8", "age9_12", "teen", "adult")
        placeholders = ",".join("?" * len(bands))
        trails = self.conn.execute(
            f"""
            SELECT t.key, t.title, t.description, t.icon, t.age_band,
                   (SELECT COUNT(*) FROM trail_station s WHERE s.trail_id = t.id) AS stations
            FROM trail t WHERE t.age_band IN ({placeholders})
            ORDER BY t.sort_order, t.title
            """,
            bands,
        ).fetchall()
        for trail in trails:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(stars), 0) AS stars FROM usr.trail_progress "
                "WHERE trail_key = ? AND completed_at IS NOT NULL",
                (trail["key"],),
            ).fetchone()
            trail["completed"] = int(row["n"])
            trail["stars"] = int(row["stars"])
        return trails

    def get_trail(self, key: str) -> dict[str, Any] | None:
        trail = self.conn.execute(
            "SELECT id, key, title, description, icon, age_band FROM trail WHERE key = ?",
            (key,),
        ).fetchone()
        if not trail:
            return None

        stations = self.conn.execute(
            """
            SELECT s.key, s.title, s.subtitle, s.icon, s.palette, s.sort_order,
                   q.key AS quiz_key, q.title AS quiz_title,
                   (SELECT COUNT(*) FROM quiz_question qq WHERE qq.quiz_id = q.id) AS questions,
                   b.key AS badge_key, b.title AS badge_title, b.icon AS badge_icon,
                   b.description AS badge_description,
                   a.slug AS article_slug, a.title AS article_title
            FROM trail_station s
            LEFT JOIN quiz q ON q.id = s.quiz_id
            LEFT JOIN badge b ON b.id = s.badge_id
            LEFT JOIN article a ON a.id = s.article_id
            WHERE s.trail_id = ? ORDER BY s.sort_order
            """,
            (trail["id"],),
        ).fetchall()

        progress = {
            r["station_key"]: r
            for r in self.conn.execute(
                "SELECT station_key, best_score, total, stars, attempts, completed_at "
                "FROM usr.trail_progress WHERE trail_key = ?",
                (key,),
            ).fetchall()
        }
        earned = self.earned_badge_keys()

        # A station unlocks when the one before it is complete. The first is
        # always open, and once a station is complete it stays open for replay.
        unlocked = True
        for station in stations:
            record = progress.get(station["key"])
            station["best_score"] = record["best_score"] if record else 0
            station["total"] = record["total"] if record else station["questions"]
            station["stars"] = record["stars"] if record else 0
            station["attempts"] = record["attempts"] if record else 0
            station["completed"] = bool(record and record["completed_at"])
            station["badge_earned"] = station["badge_key"] in earned
            station["unlocked"] = unlocked or station["completed"]
            unlocked = station["completed"]

        trail.pop("id", None)
        trail["stations"] = stations
        trail["completed"] = sum(1 for s in stations if s["completed"])
        trail["stars"] = sum(int(s["stars"]) for s in stations)
        trail["max_stars"] = len(stations) * 3
        return trail

    def earned_badge_keys(self) -> set[str]:
        return {
            r["badge_key"]
            for r in self.conn.execute("SELECT badge_key FROM usr.earned_badge").fetchall()
        }

    def badges(self) -> list[dict[str, Any]]:
        earned = {
            r["badge_key"]: r["earned_at"]
            for r in self.conn.execute(
                "SELECT badge_key, earned_at FROM usr.earned_badge"
            ).fetchall()
        }
        rows = self.conn.execute(
            "SELECT key, title, description, icon, criteria FROM badge ORDER BY sort_order, title"
        ).fetchall()
        for row in rows:
            row["earned"] = row["key"] in earned
            row["earned_at"] = earned.get(row["key"])
        return rows

    # -- writes ---------------------------------------------------------------

    def _award(self, badge_key: str | None, detail: dict[str, Any]) -> dict[str, Any] | None:
        """Award a badge if it exists and is not already held."""
        if not badge_key:
            return None
        badge = self.conn.execute(
            "SELECT key, title, description, icon FROM badge WHERE key = ?", (badge_key,)
        ).fetchone()
        if not badge:
            return None
        already = self.conn.execute(
            "SELECT 1 FROM usr.earned_badge WHERE badge_key = ?", (badge_key,)
        ).fetchone()
        if already:
            return None
        self.conn.execute(
            "INSERT INTO usr.earned_badge (badge_key, detail) VALUES (?, ?)",
            (badge_key, json.dumps(detail)),
        )
        return badge

    def record_result(
        self, trail_key: str, station_key: str, score: int, total: int
    ) -> dict[str, Any]:
        """Store a station attempt and award whatever it earns."""
        station = self.conn.execute(
            """
            SELECT s.key, s.title, b.key AS badge_key, cb.key AS completion_badge_key
            FROM trail_station s
            JOIN trail t ON t.id = s.trail_id
            LEFT JOIN badge b ON b.id = s.badge_id
            LEFT JOIN badge cb ON cb.id = t.completion_badge_id
            WHERE t.key = ? AND s.key = ?
            """,
            (trail_key, station_key),
        ).fetchone()
        if not station:
            raise KeyError(f"no station {station_key!r} on trail {trail_key!r}")

        total = max(1, int(total))
        score = max(0, min(int(score), total))
        stars = stars_for(score, total)
        passed = score / total >= PASS_RATIO
        completed_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S") if passed else None

        self.conn.execute(
            """
            INSERT INTO usr.trail_progress (trail_key, station_key, best_score, total, stars,
                                            attempts, completed_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, datetime('now'))
            ON CONFLICT(trail_key, station_key) DO UPDATE SET
                best_score = MAX(usr.trail_progress.best_score, excluded.best_score),
                total      = excluded.total,
                stars      = MAX(usr.trail_progress.stars, excluded.stars),
                attempts   = usr.trail_progress.attempts + 1,
                -- Once cleared, a station stays cleared. Replaying and doing
                -- worse should never take progress away from a child.
                completed_at = COALESCE(usr.trail_progress.completed_at, excluded.completed_at),
                updated_at = datetime('now')
            """,
            (trail_key, station_key, score, total, stars, completed_at),
        )

        detail = {"trail": trail_key, "station": station_key, "score": score, "total": total}
        awarded: list[dict[str, Any]] = []

        if passed:
            badge = self._award(station["badge_key"], detail)
            if badge:
                awarded.append(badge)

        if score == total:
            badge = self._award("perfect-round", detail)
            if badge:
                awarded.append(badge)

        # Breadth rather than score: attempted, not necessarily cleared, so it
        # rewards looking around rather than only being right.
        visited = self.conn.execute(
            "SELECT COUNT(*) AS n FROM usr.trail_progress"
        ).fetchone()
        if int(visited["n"]) >= CURIOUS_STATIONS:
            badge = self._award("curious-mind", detail)
            if badge:
                awarded.append(badge)

        # Trail completion.
        remaining = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM trail_station s
            JOIN trail t ON t.id = s.trail_id
            WHERE t.key = ? AND NOT EXISTS (
                SELECT 1 FROM usr.trail_progress p
                WHERE p.trail_key = t.key AND p.station_key = s.key
                  AND p.completed_at IS NOT NULL)
            """,
            (trail_key,),
        ).fetchone()
        if int(remaining["n"]) == 0:
            badge = self._award(station["completion_badge_key"], detail)
            if badge:
                awarded.append(badge)

        self.conn.commit()
        return {
            "trail": trail_key,
            "station": station_key,
            "score": score,
            "total": total,
            "stars": stars,
            "passed": passed,
            "badges_awarded": awarded,
        }

    def reset(self, trail_key: str | None = None) -> None:
        """Clear progress. Offered because a child may want to start again."""
        if trail_key:
            self.conn.execute("DELETE FROM usr.trail_progress WHERE trail_key = ?", (trail_key,))
        else:
            self.conn.execute("DELETE FROM usr.trail_progress")
            self.conn.execute("DELETE FROM usr.earned_badge")
        self.conn.commit()
