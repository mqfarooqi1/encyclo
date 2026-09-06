"""Article quality scoring and automated fact-checking.

Both are diagnostic. Neither ever edits content: the fact checker raises
``issue`` rows for a human to triage, and the scorer writes a number that
appears in the admin dashboard, not an assertion about truth.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from ..content.validate import CITATION_MARKER_RE
from ..domain.models import READING_LEVELS

log = logging.getLogger(__name__)

# Component weights; must sum to 1.0.
WEIGHTS = {
    "source_coverage": 0.20,
    "source_quality": 0.18,
    "citation_coverage": 0.15,
    "completeness": 0.14,
    "reading_levels": 0.13,
    "freshness": 0.10,
    "readability": 0.05,
    "media": 0.05,
}


@dataclass(slots=True)
class QualityBreakdown:
    source_coverage: int = 0
    source_quality: int = 0
    citation_coverage: int = 0
    completeness: int = 0
    reading_levels: int = 0
    freshness: int = 0
    readability: int = 0
    media: int = 0

    def total(self) -> int:
        return round(sum(getattr(self, k) * w for k, w in WEIGHTS.items()))


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> int:
    return int(max(low, min(high, value)))


class QualityService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def score_article(self, article_id: int) -> QualityBreakdown | None:
        art = self.conn.execute(
            "SELECT id, current_revision_id, next_review_at, summary FROM article WHERE id = ?",
            (article_id,),
        ).fetchone()
        if not art or not art["current_revision_id"]:
            return None
        revision_id = art["current_revision_id"]
        b = QualityBreakdown()

        contents = self.conn.execute(
            "SELECT reading_level, body_md, word_count FROM article_content WHERE revision_id = ?",
            (revision_id,),
        ).fetchall()
        adult = next((c for c in contents if c["reading_level"] == "adult"), None)
        adult_words = int(adult["word_count"]) if adult else 0

        citations = self.conn.execute(
            "SELECT ct.marker, s.tier FROM citation ct JOIN source s ON s.id = ct.source_id "
            "WHERE ct.revision_id = ?",
            (revision_id,),
        ).fetchall()

        # 1. Source coverage: roughly one citation per 150 words of adult text.
        if adult_words:
            expected = max(1.0, adult_words / 150.0)
            b.source_coverage = _clamp(len(citations) / expected * 100.0)
        elif citations:
            b.source_coverage = 50

        # 2. Source quality: tier 1 scores 100, tier 4 scores 25.
        if citations:
            tiers = [int(c["tier"]) for c in citations]
            b.source_quality = _clamp(sum((5 - t) / 4 * 100 for t in tiers) / len(tiers))

        # 3. Citation coverage of the quick-facts panel.
        facts = self.conn.execute(
            "SELECT id, epistemic FROM fact WHERE revision_id = ?", (revision_id,)
        ).fetchall()
        if facts:
            cited = self.conn.execute(
                "SELECT COUNT(DISTINCT fc.fact_id) AS n FROM fact_citation fc "
                "JOIN fact f ON f.id = fc.fact_id WHERE f.revision_id = ?",
                (revision_id,),
            ).fetchone()
            b.citation_coverage = _clamp(int(cited["n"]) / len(facts) * 100.0)
        else:
            b.citation_coverage = 40  # no facts panel is a gap, not a disaster

        # 4. Completeness.
        points = 0
        points += 25 if adult_words >= 250 else (12 if adult_words >= 120 else 0)
        points += 20 if facts else 0
        points += 15 if (art["summary"] or "").strip() else 0
        rel = self.conn.execute(
            "SELECT COUNT(*) AS n FROM relation WHERE from_article_id = ? OR to_article_id = ?",
            (article_id, article_id),
        ).fetchone()
        points += 20 if int(rel["n"]) >= 3 else (10 if int(rel["n"]) else 0)
        ev = self.conn.execute(
            "SELECT COUNT(*) AS n FROM timeline_event WHERE article_id = ?", (article_id,)
        ).fetchone()
        points += 10 if int(ev["n"]) else 0
        quiz = self.conn.execute(
            "SELECT COUNT(*) AS n FROM quiz WHERE article_id = ?", (article_id,)
        ).fetchone()
        points += 10 if int(quiz["n"]) else 0
        b.completeness = _clamp(points)

        # 5. Reading levels present.
        present = {c["reading_level"] for c in contents}
        b.reading_levels = _clamp(len(present & {lv.value for lv in READING_LEVELS}) / 4 * 100)

        # 6. Freshness relative to this article's own review schedule.
        b.freshness = self._freshness(art["next_review_at"])

        # 7. Readability: mean sentence length of the adult body in a sane band.
        if adult and adult["body_md"]:
            sentences = [s for s in re.split(r"[.!?]+", adult["body_md"]) if s.strip()]
            if sentences:
                mean = sum(len(s.split()) for s in sentences) / len(sentences)
                b.readability = _clamp(100 - abs(mean - 20) * 4)

        # 8. Media with accessible alt text.
        media = self.conn.execute(
            "SELECT role, alt_text FROM article_media WHERE article_id = ?", (article_id,)
        ).fetchall()
        if media:
            has_hero = any(m["role"] == "hero" for m in media)
            with_alt = sum(1 for m in media if (m["alt_text"] or "").strip())
            b.media = _clamp((60 if has_hero else 30) + with_alt / len(media) * 40)

        total = b.total()
        self.conn.execute(
            """
            INSERT INTO quality_report (article_id, total, source_coverage, source_quality,
                freshness, completeness, readability, reading_levels, citation_coverage, media,
                computed_at, detail_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),'{}')
            ON CONFLICT(article_id) DO UPDATE SET
                total=excluded.total, source_coverage=excluded.source_coverage,
                source_quality=excluded.source_quality, freshness=excluded.freshness,
                completeness=excluded.completeness, readability=excluded.readability,
                reading_levels=excluded.reading_levels,
                citation_coverage=excluded.citation_coverage, media=excluded.media,
                computed_at=datetime('now')
            """,
            (
                article_id, total, b.source_coverage, b.source_quality, b.freshness,
                b.completeness, b.readability, b.reading_levels, b.citation_coverage, b.media,
            ),
        )
        self.conn.execute("UPDATE article SET quality_score = ? WHERE id = ?", (total, article_id))
        return b

    @staticmethod
    def _freshness(next_review_at: str | None) -> int:
        """An article is not wrong because it is old -- it is only *due*.

        Score degrades once the article passes its own review date, and never
        below 40, because an overdue review is a scheduling fact, not evidence
        that the content is incorrect.
        """
        if not next_review_at:
            return 60
        try:
            due = datetime.strptime(next_review_at, "%Y-%m-%d").date()
        except ValueError:
            return 60
        days_left = (due - date.today()).days
        if days_left >= 0:
            return 100
        overdue_months = -days_left / 30.0
        return _clamp(100 - overdue_months * 8, low=40)

    def score_all(self) -> dict[str, Any]:
        ids = [
            r["id"]
            for r in self.conn.execute(
                "SELECT id FROM article WHERE status = 'published'"
            ).fetchall()
        ]
        scores: list[int] = []
        for article_id in ids:
            breakdown = self.score_article(article_id)
            if breakdown:
                scores.append(breakdown.total())
        self.conn.commit()
        return {
            "scored": len(scores),
            "average": round(sum(scores) / len(scores), 1) if scores else 0,
            "lowest": min(scores) if scores else None,
            "highest": max(scores) if scores else None,
        }

    def breakdown(self, slug: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT qr.* FROM quality_report qr JOIN article a ON a.id = qr.article_id "
            "WHERE a.slug = ?",
            (slug,),
        ).fetchone()
        if not row:
            return None
        row["weights"] = WEIGHTS
        return row


class FactChecker:
    """Automated integrity checks. Flags, never corrects."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def run(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        self.conn.execute(
            "UPDATE issue SET status = 'resolved', resolved_at = datetime('now') "
            "WHERE status = 'open' AND kind IN "
            "('missing_citation','unsupported_claim','missing_alt_text','outdated',"
            "'inconsistent_unit','broken_source','duplicate_article')"
        )
        for name, fn in (
            ("missing_citation", self._missing_citations),
            ("unsupported_claim", self._dangling_markers),
            ("missing_alt_text", self._missing_alt_text),
            ("outdated", self._overdue_review),
            ("broken_source", self._broken_sources),
            ("duplicate_article", self._duplicate_titles),
            ("inconsistent_unit", self._inconsistent_units),
        ):
            counts[name] = fn()
        self.conn.commit()
        return counts

    def _raise(self, article_id: int | None, kind: str, severity: str, detail: str,
               source_id: int | None = None) -> None:
        self.conn.execute(
            "INSERT INTO issue (article_id, source_id, kind, severity, detail) VALUES (?,?,?,?,?)",
            (article_id, source_id, kind, severity, detail),
        )

    def _missing_citations(self) -> int:
        rows = self.conn.execute(
            "SELECT a.id, a.slug FROM article a WHERE a.status = 'published' "
            "AND NOT EXISTS (SELECT 1 FROM citation c WHERE c.revision_id = a.current_revision_id)"
        ).fetchall()
        for row in rows:
            self._raise(row["id"], "missing_citation", "error",
                        f"{row['slug']} is published with no citations at all")
        return len(rows)

    def _dangling_markers(self) -> int:
        found = 0
        rows = self.conn.execute(
            "SELECT a.id, a.slug, a.current_revision_id AS rev FROM article a "
            "WHERE a.status = 'published'"
        ).fetchall()
        for row in rows:
            bodies = self.conn.execute(
                "SELECT body_md FROM article_content WHERE revision_id = ?", (row["rev"],)
            ).fetchall()
            used = set()
            for body in bodies:
                used |= {int(m) for m in CITATION_MARKER_RE.findall(body["body_md"] or "")}
            defined = {
                int(r["marker"])
                for r in self.conn.execute(
                    "SELECT marker FROM citation WHERE revision_id = ?", (row["rev"],)
                ).fetchall()
            }
            for missing in sorted(used - defined):
                self._raise(row["id"], "unsupported_claim", "error",
                            f"{row['slug']} cites [{missing}] but no such citation exists")
                found += 1
        return found

    def _missing_alt_text(self) -> int:
        rows = self.conn.execute(
            "SELECT am.article_id, a.slug, m.uid FROM article_media am "
            "JOIN media m ON m.id = am.media_id JOIN article a ON a.id = am.article_id "
            "WHERE TRIM(COALESCE(am.alt_text, '')) = ''"
        ).fetchall()
        for row in rows:
            self._raise(row["article_id"], "missing_alt_text", "warning",
                        f"{row['slug']}: media {row['uid']} has no alt text")
        return len(rows)

    def _overdue_review(self) -> int:
        rows = self.conn.execute(
            "SELECT id, slug, next_review_at FROM article WHERE status = 'published' "
            "AND next_review_at IS NOT NULL AND next_review_at < date('now')"
        ).fetchall()
        for row in rows:
            self._raise(row["id"], "outdated", "info",
                        f"{row['slug']} was due for review on {row['next_review_at']}")
        return len(rows)

    def _broken_sources(self) -> int:
        rows = self.conn.execute(
            "SELECT id, uid, verification_status FROM source "
            "WHERE verification_status IN ('broken','moved')"
        ).fetchall()
        for row in rows:
            self._raise(None, "broken_source", "error",
                        f"source {row['uid']} is {row['verification_status']}",
                        source_id=row["id"])
        return len(rows)

    def _duplicate_titles(self) -> int:
        rows = self.conn.execute(
            "SELECT lower(title) AS t, COUNT(*) AS n, group_concat(slug, ', ') AS slugs "
            "FROM article WHERE status = 'published' GROUP BY lower(title) HAVING n > 1"
        ).fetchall()
        for row in rows:
            self._raise(None, "duplicate_article", "warning",
                        f"{row['n']} articles share the title {row['t']!r}: {row['slugs']}")
        return len(rows)

    def _inconsistent_units(self) -> int:
        """Facts sharing a comparable_key should share a unit, or a comparison
        table will silently put centimetres next to metres.

        Scoped to current revisions only. Revision history is append-only, so
        scanning every revision would re-report a conflict that has already been
        fixed, for as long as the superseded revision exists -- which is forever.
        """
        rows = self.conn.execute(
            "SELECT f.comparable_key, COUNT(DISTINCT COALESCE(f.unit,'')) AS units, "
            "group_concat(DISTINCT COALESCE(f.unit,'(none)')) AS unit_list "
            "FROM fact f "
            "JOIN article a ON a.current_revision_id = f.revision_id "
            "WHERE f.comparable_key IS NOT NULL AND a.status = 'published' "
            "GROUP BY f.comparable_key HAVING units > 1"
        ).fetchall()
        for row in rows:
            self._raise(None, "inconsistent_unit", "warning",
                        f"comparable '{row['comparable_key']}' mixes units: {row['unit_list']}")
        return len(rows)


def breakdown_to_dict(b: QualityBreakdown) -> dict[str, Any]:
    data = asdict(b)
    data["total"] = b.total()
    return data
