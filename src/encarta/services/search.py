"""Search: indexing, query building, ranking and did-you-mean correction.

Ranking deliberately does *not* reduce to popularity (requirement 39). The final
score blends lexical relevance with signals about how trustworthy and how
suitable the article is:

    exact title match  >  lexical relevance (bm25)  >  source quality  >  age fit

User input never reaches FTS5 as raw syntax. Queries are tokenised and each term
is re-quoted, so a stray ``"`` or ``NEAR(`` cannot produce a syntax error or
change the shape of the query.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..domain.models import READING_LEVELS, ReadingLevel

log = logging.getLogger(__name__)

# Column weights for bm25(): title, aliases, summary, body, facts, categories.
# A title hit should beat a passing mention in a long body.
_BM25_WEIGHTS = (12.0, 9.0, 4.0, 1.0, 2.5, 2.0)

_TOKEN_RE = re.compile(r"[^\w\s'-]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")

# Words that add nothing to a lexical match but appear constantly in natural
# questions ("what is the largest dinosaur").
_STOPWORDS = frozenset(
    ["a", "an", "the", "of", "in", "on", "at", "to", "for", "is", "are", "was", "were", "be", "been", "being", "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "do", "does", "did", "can", "could", "would", "should", "i", "my", "me", "you", "your", "it", "its", "this", "that", "these", "those", "and", "or", "but", "if", "then", "than", "there", "here", "about"]
)


@dataclass(slots=True)
class SearchHit:
    slug: str
    title: str
    summary: str
    type_key: str
    type_label: str
    category: str | None
    category_icon: str | None
    score: float
    relevance: float
    quality_score: int | None
    hero_media: str | None = None
    matched_alias: str | None = None
    available_levels: list[str] = field(default_factory=list)
    snippet: str = ""


@dataclass(slots=True)
class SearchResponse:
    query: str
    hits: list[SearchHit]
    total: int
    corrected_query: str | None = None
    suggestions: list[str] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    took_ms: float = 0.0


def tokenize(text: str) -> list[str]:
    """Split a user query into safe, lowercase terms."""
    cleaned = _TOKEN_RE.sub(" ", text or "")
    return [t for t in _WS_RE.split(cleaned.strip().lower()) if t]


def build_match_expression(
    terms: list[str], *, prefix: bool = True, require_all: bool = False
) -> str:
    """Build a safe FTS5 MATCH expression from already-tokenised terms.

    Every term is wrapped in double quotes (with internal quotes doubled), which
    makes it a literal string token to FTS5 regardless of its content.

    ``require_all`` switches OR to AND. Browsing search wants OR — a partial
    match is still a useful result. Retrieval for answering wants AND: with OR,
    a question about a topic the encyclopaedia has never covered still matches
    any article sharing one common word, which would let the assistant believe
    it had grounding when it had none.
    """
    parts: list[str] = []
    for term in terms:
        safe = term.replace('"', '""')
        parts.append(f'"{safe}"*' if prefix and len(term) >= 3 else f'"{safe}"')
    return (" AND " if require_all else " OR ").join(parts)


def _damerau_levenshtein(a: str, b: str, max_distance: int = 2) -> int:
    """Bounded edit distance, used only for short dictionary terms."""
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    prev_prev: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev_prev[j - 2] + cost)
        if min(cur) > max_distance:
            return max_distance + 1
        prev_prev, prev = prev, cur
    return prev[-1]


class SearchIndexer:
    """Rebuilds the FTS index from published current revisions only.

    Draft and archived articles are never indexed, so an unreviewed edit cannot
    become discoverable by accident.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _indexable_rows(self, article_id: int | None = None) -> list[dict[str, Any]]:
        where = "a.status = 'published' AND a.current_revision_id IS NOT NULL"
        params: tuple[Any, ...] = ()
        if article_id is not None:
            where += " AND a.id = ?"
            params = (article_id,)
        return self.conn.execute(
            f"""
            SELECT a.id, a.title, a.summary,
                   COALESCE((SELECT group_concat(alias, ' ') FROM article_alias
                             WHERE article_id = a.id), '') AS aliases,
                   COALESCE((SELECT group_concat(body_md, char(10))
                             FROM article_content WHERE revision_id = a.current_revision_id), '')
                       AS body,
                   COALESCE((SELECT group_concat(label || ' ' || value_text, ' ')
                             FROM fact WHERE revision_id = a.current_revision_id), '') AS facts,
                   COALESCE((SELECT group_concat(c.label, ' ') FROM article_category ac
                             JOIN category c ON c.id = ac.category_id
                             WHERE ac.article_id = a.id), '') AS categories
            FROM article a
            WHERE {where}
            """,
            params,
        ).fetchall()

    def rebuild(self) -> int:
        rows = self._indexable_rows()
        self.conn.execute("DELETE FROM article_fts")
        self.conn.executemany(
            "INSERT INTO article_fts (rowid, title, aliases, summary, body, facts, categories) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (r["id"], r["title"], r["aliases"], r["summary"], r["body"], r["facts"],
                 r["categories"])
                for r in rows
            ],
        )
        self.conn.execute("INSERT INTO article_fts(article_fts) VALUES ('optimize')")
        self.conn.commit()
        log.info("search index rebuilt: %d articles", len(rows))
        return len(rows)

    def reindex_article(self, article_id: int) -> None:
        self.conn.execute("DELETE FROM article_fts WHERE rowid = ?", (article_id,))
        for r in self._indexable_rows(article_id):
            self.conn.execute(
                "INSERT INTO article_fts (rowid, title, aliases, summary, body, facts, categories)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["id"], r["title"], r["aliases"], r["summary"], r["body"], r["facts"],
                 r["categories"]),
            )
        self.conn.commit()


class SearchService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- query expansion ---------------------------------------------------

    def _expand(self, terms: list[str]) -> list[str]:
        """Add synonym expansions so 'T rex' or 'largest dinosaur' still lands."""
        if not terms:
            return terms
        placeholders = ",".join("?" * len(terms))
        rows = self.conn.execute(
            f"SELECT term, expands_to FROM synonym WHERE term IN ({placeholders})",
            terms,
        ).fetchall()
        # Also try the whole phrase, so multi-word synonyms work.
        phrase = " ".join(terms)
        rows += self.conn.execute(
            "SELECT term, expands_to FROM synonym WHERE term = ?", (phrase,)
        ).fetchall()
        extra: list[str] = []
        for row in rows:
            extra.extend(tokenize(row["expands_to"]))
        seen = set(terms)
        deduped: list[str] = []
        for term in extra:
            if term not in seen:
                seen.add(term)
                deduped.append(term)
        return terms + deduped

    def suggest_correction(self, terms: list[str]) -> tuple[str | None, list[str]]:
        """Offer a did-you-mean using the index's own term dictionary."""
        corrections: list[str] = []
        changed = False
        for term in terms:
            if len(term) < 4:
                corrections.append(term)
                continue
            exists = self.conn.execute(
                "SELECT 1 FROM article_fts_vocab WHERE term = ? LIMIT 1", (term,)
            ).fetchone()
            if exists:
                corrections.append(term)
                continue
            candidates = self.conn.execute(
                "SELECT term, cnt FROM article_fts_vocab "
                "WHERE length(term) BETWEEN ? AND ? AND substr(term, 1, 1) = substr(?, 1, 1) "
                "ORDER BY cnt DESC LIMIT 400",
                (len(term) - 2, len(term) + 2, term),
            ).fetchall()
            best, best_dist = None, 3
            for cand in candidates:
                dist = _damerau_levenshtein(term, cand["term"])
                if dist < best_dist:
                    best, best_dist = cand["term"], dist
            if best:
                corrections.append(best)
                changed = True
            else:
                corrections.append(term)
        return (" ".join(corrections) if changed else None), corrections

    # -- search -------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        category: str | None = None,
        type_key: str | None = None,
        reading_level: str | None = None,
        kids_only: bool = False,
        require_all: bool = False,
    ) -> SearchResponse:
        import time

        started = time.perf_counter()
        raw_terms = tokenize(query)
        terms = [t for t in raw_terms if t not in _STOPWORDS] or raw_terms
        if not terms:
            return SearchResponse(query=query, hits=[], total=0)

        # Synonym expansion would defeat an AND query, since the expansions are
        # alternatives rather than additional requirements.
        expanded = terms if require_all else self._expand(terms)
        match_expr = build_match_expression(expanded, require_all=require_all)

        corrected: str | None = None
        try:
            rows = self._run(
                match_expr, limit, offset, category, type_key, reading_level, kids_only
            )
        except sqlite3.OperationalError as exc:
            log.warning("FTS query failed for %r: %s", query, exc)
            rows = []

        # Nothing found: try a spelling correction before giving up.
        if not rows and not require_all:
            corrected, corrected_terms = self.suggest_correction(terms)
            if corrected:
                try:
                    rows = self._run(
                        build_match_expression(self._expand(corrected_terms)),
                        limit,
                        offset,
                        category,
                        type_key,
                        reading_level,
                        kids_only,
                    )
                except sqlite3.OperationalError:
                    rows = []

        # SQL orders by bm25 alone, which is only the lexical component. The
        # final score also folds in exact-title match, source strength and
        # article quality, so the ranking must be re-sorted here or those
        # signals never actually affect the order the reader sees.
        hits = sorted(
            (self._to_hit(r, terms) for r in rows), key=lambda h: -h.score
        )
        return SearchResponse(
            query=query,
            hits=hits,
            total=len(hits),
            corrected_query=corrected,
            expanded_terms=[t for t in expanded if t not in terms],
            took_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def _run(
        self,
        match_expr: str,
        limit: int,
        offset: int,
        category: str | None,
        type_key: str | None,
        reading_level: str | None,
        kids_only: bool,
    ) -> list[dict[str, Any]]:
        clauses = ["a.status = 'published'"]
        params: list[Any] = [match_expr]
        if category:
            clauses.append(
                "EXISTS (SELECT 1 FROM article_category ac JOIN category c ON c.id = ac.category_id"
                " WHERE ac.article_id = a.id AND c.key = ?)"
            )
            params.append(category)
        if type_key:
            clauses.append("t.key = ?")
            params.append(type_key)
        if reading_level:
            clauses.append(
                "EXISTS (SELECT 1 FROM article_content ic WHERE ic.revision_id = "
                "a.current_revision_id AND ic.reading_level = ?)"
            )
            params.append(reading_level)
        if kids_only:
            clauses.append("a.kids_safe = 1")
        params.extend([limit, offset])

        sql = f"""
            SELECT a.slug, a.title, a.summary, a.quality_score, a.min_reading_level,
                   t.key AS type_key, t.label AS type_label,
                   bm25(article_fts, {", ".join(str(w) for w in _BM25_WEIGHTS)}) AS bm25_score,
                   snippet(article_fts, 3, '<mark>', '</mark>', ' ... ', 24) AS snippet,
                   (SELECT c.label FROM article_category ac JOIN category c ON c.id = ac.category_id
                     WHERE ac.article_id = a.id ORDER BY ac.is_primary DESC LIMIT 1) AS category,
                   (SELECT c.icon FROM article_category ac JOIN category c ON c.id = ac.category_id
                     WHERE ac.article_id = a.id ORDER BY ac.is_primary DESC LIMIT 1) AS category_icon,
                   (SELECT m.local_path FROM article_media am JOIN media m ON m.id = am.media_id
                     WHERE am.article_id = a.id AND am.role = 'hero' LIMIT 1) AS hero_media,
                   (SELECT group_concat(ic.reading_level) FROM article_content ic
                     WHERE ic.revision_id = a.current_revision_id) AS levels,
                   (SELECT AVG(5 - s.tier) FROM citation ct JOIN source s ON s.id = ct.source_id
                     WHERE ct.revision_id = a.current_revision_id) AS source_strength
            FROM article_fts
            JOIN article a ON a.id = article_fts.rowid
            JOIN article_type t ON t.id = a.type_id
            WHERE article_fts MATCH ? AND {" AND ".join(clauses)}
            ORDER BY bm25_score
            LIMIT ? OFFSET ?
        """
        return self.conn.execute(sql, params).fetchall()

    def _to_hit(self, row: dict[str, Any], terms: list[str]) -> SearchHit:
        # bm25 returns negative numbers, more negative meaning a better match.
        relevance = -float(row["bm25_score"] or 0.0)
        title_lower = (row["title"] or "").lower()
        query_join = " ".join(terms)

        score = relevance
        if title_lower == query_join:
            score += 100.0          # exact title wins outright
        elif title_lower.startswith(query_join):
            score += 40.0
        elif all(t in title_lower for t in terms):
            score += 15.0

        # Trust signals: better-sourced and higher-quality articles rank above
        # equally-relevant but thinly-sourced ones.
        strength = row.get("source_strength")
        if strength is not None:
            score += float(strength) * 3.0
        if row.get("quality_score") is not None:
            score += float(row["quality_score"]) / 20.0

        order = [lv.value for lv in READING_LEVELS]
        levels = sorted(
            (lv for lv in (row.get("levels") or "").split(",") if lv in order),
            key=order.index,
        )
        return SearchHit(
            slug=row["slug"],
            title=row["title"],
            summary=row["summary"] or "",
            type_key=row["type_key"],
            type_label=row["type_label"],
            category=row.get("category"),
            category_icon=row.get("category_icon"),
            score=round(score, 3),
            relevance=round(relevance, 3),
            quality_score=row.get("quality_score"),
            hero_media=row.get("hero_media"),
            available_levels=levels,
            snippet=row.get("snippet") or "",
        )

    def autocomplete(self, prefix: str, limit: int = 8, kids_only: bool = False) -> list[dict[str, Any]]:
        """As-you-type suggestions from titles and aliases."""
        terms = tokenize(prefix)
        if not terms:
            return []
        like = f"{' '.join(terms)}%"
        kids_clause = " AND a.kids_safe = 1" if kids_only else ""
        return self.conn.execute(
            f"""
            SELECT DISTINCT a.slug, a.title, t.label AS type_label,
                   (SELECT c.icon FROM article_category ac JOIN category c ON c.id = ac.category_id
                     WHERE ac.article_id = a.id ORDER BY ac.is_primary DESC LIMIT 1) AS icon,
                   CASE WHEN lower(a.title) LIKE ? THEN 0 ELSE 1 END AS rank_bucket,
                   a.title AS label
            FROM article a
            JOIN article_type t ON t.id = a.type_id
            LEFT JOIN article_alias al ON al.article_id = a.id
            WHERE a.status = 'published'{kids_clause}
              AND (lower(a.title) LIKE ? OR lower(al.alias) LIKE ?)
            ORDER BY rank_bucket, length(a.title), a.title
            LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()


def resolve_requested_level(requested: str | None, available: list[str]) -> str | None:
    """Public helper used by the API when serving an article at a level."""
    if not available:
        return None
    want = requested or ReadingLevel.ADULT.value
    order = [lv.value for lv in READING_LEVELS]
    if want not in order:
        want = ReadingLevel.ADULT.value
    index = order.index(want)
    for candidate in [*order[index:], *reversed(order[:index])]:
        if candidate in available:
            return candidate
    return None
