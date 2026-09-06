"""Discovery reads: the home page, categories, timeline, and random exploration."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any


class DiscoveryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def categories(self, kids_only: bool = False) -> list[dict[str, Any]]:
        kids = " AND c.kids_safe = 1" if kids_only else ""
        article_kids = " AND a.kids_safe = 1" if kids_only else ""
        return self.conn.execute(
            f"""
            SELECT c.key, c.label, c.icon, c.description, c.sort_order,
                   (SELECT COUNT(*) FROM article_category ac JOIN article a ON a.id = ac.article_id
                     WHERE ac.category_id = c.id AND a.status = 'published'{article_kids})
                     AS article_count
            FROM category c
            WHERE c.parent_id IS NULL{kids}
            ORDER BY c.sort_order, c.label
            """,
        ).fetchall()

    def stats(self) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM article WHERE status = 'published') AS articles,
              (SELECT COUNT(*) FROM source)                             AS sources,
              (SELECT COUNT(*) FROM media)                              AS media,
              (SELECT COUNT(*) FROM relation)                           AS relations,
              (SELECT COUNT(*) FROM timeline_event)                     AS events,
              (SELECT COUNT(*) FROM quiz)                               AS quizzes,
              (SELECT COUNT(*) FROM learning_path)                      AS paths,
              (SELECT COUNT(*) FROM category)                           AS categories,
              (SELECT COUNT(*) FROM issue WHERE status = 'open')        AS open_issues,
              (SELECT ROUND(AVG(quality_score), 1) FROM article
                WHERE quality_score IS NOT NULL)                        AS avg_quality
            """
        ).fetchone()
        return row or {}

    def _card_query(self, where: str, order: str, limit: int, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return self.conn.execute(
            f"""
            SELECT a.slug, a.title, a.summary, a.quality_score, t.label AS type_label,
                   t.key AS type_key,
                   (SELECT c.icon FROM article_category ac JOIN category c ON c.id = ac.category_id
                     WHERE ac.article_id = a.id ORDER BY ac.is_primary DESC LIMIT 1) AS icon,
                   (SELECT c.label FROM article_category ac JOIN category c ON c.id = ac.category_id
                     WHERE ac.article_id = a.id ORDER BY ac.is_primary DESC LIMIT 1) AS category,
                   (SELECT m.local_path FROM article_media am JOIN media m ON m.id = am.media_id
                     WHERE am.article_id = a.id AND am.role = 'hero' LIMIT 1) AS hero_media,
                   (SELECT group_concat(ic.reading_level) FROM article_content ic
                     WHERE ic.revision_id = a.current_revision_id) AS levels
            FROM article a JOIN article_type t ON t.id = a.type_id
            WHERE a.status = 'published' AND {where}
            ORDER BY {order}
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

    def featured(self, limit: int = 6, kids_only: bool = False) -> list[dict[str, Any]]:
        """Best-evidenced articles, not the most-clicked ones."""
        kids = "a.kids_safe = 1 AND " if kids_only else ""
        return self._card_query(
            f"{kids}a.quality_score IS NOT NULL",
            "a.quality_score DESC, a.title",
            limit,
        )

    #: Articles below this score are in the library but not in the shop window.
    #: Without it, importing thousands of reference extracts would statistically
    #: guarantee the home page showcased one of them rather than the
    #: encyclopaedia's own work.
    #:
    #: 70 is not arbitrary. The two populations do not overlap: an authored
    #: article scores 81-95 (four written levels, structured facts, tier-1
    #: citations, a quiz, relations), an imported lead section 39-62 — it has
    #: none of those and cannot score higher however good the prose is. 70 sits
    #: in the empty gap between them, so the floor is a statement about
    #: editorial completeness rather than a threshold tuned to one import.
    SHOWCASE_FLOOR = 70

    def _showcase(self, where: str, order: str, limit: int,
                  params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """A card query that prefers editorially complete articles.

        Tops up from the rest of the library when too little clears the floor,
        so a fresh install with a small pack still has a full home page — and
        keeps the good rows it did find rather than discarding them.
        """
        rows = self._card_query(
            f"({where}) AND a.quality_score >= {self.SHOWCASE_FLOOR}", order, limit, params)
        if len(rows) >= limit:
            return rows
        seen = {r["slug"] for r in rows}
        for row in self._card_query(where, order, limit, params):
            if len(rows) >= limit:
                break
            if row["slug"] not in seen:
                rows.append(row)
        return rows

    def daily_discovery(self, kids_only: bool = False) -> dict[str, Any] | None:
        """A deterministic pick of the day, so the home page is stable all day
        but different tomorrow."""
        seed = date.today().toordinal()
        kids = "a.kids_safe = 1 AND " if kids_only else ""
        rows = self._showcase(f"{kids}1 = 1", f"(a.id * 7919 + {seed}) % 10007", 1)
        return rows[0] if rows else None

    def random(self, category: str | None = None, kids_only: bool = False) -> dict[str, Any] | None:
        kids = "a.kids_safe = 1 AND " if kids_only else ""
        if category and category != "everything":
            where = (
                f"{kids}EXISTS (SELECT 1 FROM article_category ac JOIN category c "
                "ON c.id = ac.category_id WHERE ac.article_id = a.id AND c.key = ?)"
            )
            rows = self._card_query(where, "RANDOM()", 1, (category,))
        else:
            rows = self._card_query(f"{kids}1 = 1", "RANDOM()", 1)
        return rows[0] if rows else None

    def recently_updated(self, limit: int = 6, kids_only: bool = False) -> list[dict[str, Any]]:
        # Bulk-loading a content pack stamps every row with the same timestamp,
        # so this must also be quality-gated or an import erases the section.
        kids = "a.kids_safe = 1 AND " if kids_only else ""
        return self._showcase(f"{kids}1 = 1", "a.updated_at DESC, a.title", limit)

    def did_you_know(self, limit: int = 5, kids_only: bool = False) -> list[dict[str, Any]]:
        """Surprising quick-facts, always carrying their article and status."""
        kids = " AND a.kids_safe = 1" if kids_only else ""
        seed = date.today().toordinal()
        return self.conn.execute(
            f"""
            SELECT f.label, f.value_text, f.unit, f.epistemic, a.slug, a.title
            FROM fact f
            JOIN article a ON a.current_revision_id = f.revision_id
            WHERE a.status = 'published' AND f.epistemic IN ('fact','estimate')
              AND length(f.value_text) BETWEEN 2 AND 90{kids}
            ORDER BY (f.id * 6301 + {seed}) % 9973
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def on_this_day(self, limit: int = 5) -> list[dict[str, Any]]:
        """Timeline events sharing today's calendar day, where the date is known
        precisely enough to make the claim honest."""
        today = date.today()
        return self.conn.execute(
            """
            SELECT te.title, te.description, te.start_year, te.precision, te.epistemic,
                   a.slug, a.title AS article_title
            FROM timeline_event te
            LEFT JOIN article a ON a.id = te.article_id
            WHERE te.precision IN ('exact','year')
              AND te.start_year = CAST(strftime('%Y', 'now') AS REAL) - ?
            ORDER BY te.importance DESC
            LIMIT ?
            """,
            (0, limit),
        ).fetchall() or self._fallback_events(today, limit)

    def _fallback_events(self, today: date, limit: int) -> list[dict[str, Any]]:
        """No event for today's exact date: show notable anniversaries instead,
        labelled as such by the caller rather than pretending they are today."""
        return self.conn.execute(
            """
            SELECT te.title, te.description, te.start_year, te.precision, te.epistemic,
                   a.slug, a.title AS article_title
            FROM timeline_event te
            LEFT JOIN article a ON a.id = te.article_id
            WHERE te.importance >= 4
            ORDER BY (te.id * 5449 + ?) % 8867
            LIMIT ?
            """,
            (today.toordinal(), limit),
        ).fetchall()

    def timeline(
        self,
        start_year: float | None = None,
        end_year: float | None = None,
        limit: int = 300,
        min_importance: int = 1,
    ) -> list[dict[str, Any]]:
        clauses = ["te.importance >= ?"]
        params: list[Any] = [min_importance]
        if start_year is not None:
            clauses.append("COALESCE(te.end_year, te.start_year) >= ?")
            params.append(start_year)
        if end_year is not None:
            clauses.append("te.start_year <= ?")
            params.append(end_year)
        params.append(limit)
        return self.conn.execute(
            f"""
            SELECT te.id, te.title, te.description, te.start_year, te.end_year, te.precision,
                   te.era, te.importance, te.epistemic, a.slug, c.icon, c.label AS category
            FROM timeline_event te
            LEFT JOIN article a ON a.id = te.article_id
            LEFT JOIN category c ON c.id = te.category_id
            WHERE {" AND ".join(clauses)}
            ORDER BY te.start_year
            LIMIT ?
            """,
            params,
        ).fetchall()

    def places(self, kids_only: bool = False) -> list[dict[str, Any]]:
        kids = " AND a.kids_safe = 1" if kids_only else ""
        return self.conn.execute(
            f"""
            SELECT p.name, p.kind, p.lat, p.lon, p.country_code, p.from_year, p.to_year,
                   a.slug, a.title, c.icon
            FROM place p
            LEFT JOIN article a ON a.id = p.article_id AND a.status = 'published'
            LEFT JOIN article_category ac ON ac.article_id = a.id AND ac.is_primary = 1
            LEFT JOIN category c ON c.id = ac.category_id
            WHERE p.lat IS NOT NULL AND p.lon IS NOT NULL{kids}
            """,
        ).fetchall()

    def learning_paths(self, kids_only: bool = False) -> list[dict[str, Any]]:
        bands = ("age6_8", "age9_12") if kids_only else ("age6_8", "age9_12", "teen", "adult")
        placeholders = ",".join("?" * len(bands))
        return self.conn.execute(
            f"""
            SELECT lp.key, lp.title, lp.description, lp.icon, lp.age_band,
                   (SELECT COUNT(*) FROM learning_path_step s WHERE s.path_id = lp.id) AS steps
            FROM learning_path lp
            WHERE lp.age_band IN ({placeholders})
            ORDER BY lp.title
            """,
            bands,
        ).fetchall()

    def learning_path(self, key: str) -> dict[str, Any] | None:
        path = self.conn.execute(
            "SELECT key, title, description, icon, age_band FROM learning_path WHERE key = ?",
            (key,),
        ).fetchone()
        if not path:
            return None
        path["steps"] = self.conn.execute(
            """
            SELECT s.sort_order, s.note, a.slug, a.title, a.summary,
                   (SELECT c.icon FROM article_category ac JOIN category c ON c.id = ac.category_id
                     WHERE ac.article_id = a.id ORDER BY ac.is_primary DESC LIMIT 1) AS icon
            FROM learning_path_step s
            JOIN learning_path lp ON lp.id = s.path_id
            JOIN article a ON a.id = s.article_id
            WHERE lp.key = ? AND a.status = 'published'
            ORDER BY s.sort_order
            """,
            (key,),
        ).fetchall()
        return path
