"""Article reads.

Everything the article page needs, assembled from the *current published
revision* only. A draft revision is invisible here by construction, so an
unreviewed edit can never leak into the reader-facing app.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..domain.models import (
    EPISTEMIC_LABELS,
    INVERSE_RELATION_LABELS,
    READING_LEVELS,
    RELATION_LABELS,
    Epistemic,
    RelationKind,
)
from ..services.search import resolve_requested_level


class ArticleRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- lookups -----------------------------------------------------------

    def resolve_slug(self, slug: str) -> str | None:
        """Resolve a slug directly, or via an alias, so old links keep working."""
        row = self.conn.execute(
            "SELECT slug FROM article WHERE slug = ? AND status = 'published'", (slug,)
        ).fetchone()
        if row:
            return row["slug"]
        # Aliases are written as people write them ("T. rex", "T-rex"), while a
        # URL segment is kebab-case. Try both readings before giving up, so old
        # or hand-typed links keep resolving.
        candidates = {slug, slug.replace("-", " "), slug.replace("-", ". ")}
        placeholders = ",".join("?" * len(candidates))
        row = self.conn.execute(
            f"SELECT a.slug FROM article_alias al JOIN article a ON a.id = al.article_id "
            f"WHERE lower(al.alias) IN ({placeholders}) AND a.status = 'published' LIMIT 1",
            [c.lower() for c in candidates],
        ).fetchone()
        return row["slug"] if row else None

    def available_levels(self, slug: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT ic.reading_level FROM article a "
            "JOIN article_content ic ON ic.revision_id = a.current_revision_id "
            "WHERE a.slug = ?",
            (slug,),
        ).fetchall()
        order = [lv.value for lv in READING_LEVELS]
        return sorted((r["reading_level"] for r in rows if r["reading_level"] in order),
                      key=order.index)

    def get(self, slug: str, reading_level: str | None = None) -> dict[str, Any] | None:
        base = self.conn.execute(
            """
            SELECT a.id, a.slug, a.title, a.summary, a.pronunciation_ipa, a.kids_safe,
                   a.quality_score, a.last_reviewed_at, a.next_review_at, a.updated_at,
                   a.current_revision_id,
                   t.key AS type_key, t.label AS type_label, t.icon AS type_icon,
                   r.version_major, r.version_minor, r.origin, r.created_at AS revision_created_at,
                   r.change_reason, r.reviewed_by, r.ai_model
            FROM article a
            JOIN article_type t ON t.id = a.type_id
            LEFT JOIN article_revision r ON r.id = a.current_revision_id
            WHERE a.slug = ? AND a.status = 'published'
            """,
            (slug,),
        ).fetchone()
        if not base:
            return None

        article_id = base["id"]
        revision_id = base["current_revision_id"]

        levels = self.available_levels(slug)
        chosen = resolve_requested_level(reading_level, levels)
        content = None
        if chosen:
            content = self.conn.execute(
                "SELECT reading_level, summary, body_md, word_count, reading_time_min "
                "FROM article_content WHERE revision_id = ? AND reading_level = ?",
                (revision_id, chosen),
            ).fetchone()

        facts = self.conn.execute(
            """
            SELECT f.id, f.key, f.label, f.value_text, f.value_num, f.unit, f.epistemic,
                   f.confidence, f.group_label, f.comparable_key,
                   (SELECT group_concat(c.marker) FROM fact_citation fc
                     JOIN citation c ON c.id = fc.citation_id
                     WHERE fc.fact_id = f.id) AS markers
            FROM fact f WHERE f.revision_id = ? ORDER BY f.sort_order
            """,
            (revision_id,),
        ).fetchall()
        for fact in facts:
            status = Epistemic(fact["epistemic"])
            fact["epistemic_label"] = EPISTEMIC_LABELS[status]
            fact["needs_qualifier"] = status is not Epistemic.FACT
            fact["citations"] = sorted(
                int(m) for m in (fact.pop("markers") or "").split(",") if m
            )

        citations = self.conn.execute(
            """
            SELECT ct.marker, ct.claim, ct.locator, ct.quote, ct.supports,
                   s.uid AS source_uid, s.title AS source_title, s.publisher, s.authors,
                   s.url, s.doi, s.tier, s.published_date, s.accessed_date,
                   s.source_type, s.verification_status, s.license
            FROM citation ct JOIN source s ON s.id = ct.source_id
            WHERE ct.revision_id = ? ORDER BY ct.marker
            """,
            (revision_id,),
        ).fetchall()

        media = self.conn.execute(
            """
            SELECT m.uid, m.kind, m.title, m.creator, m.credit_line, m.license, m.license_url,
                   m.source_url, m.local_path, m.is_redistributable, m.provenance, m.width,
                   m.height, am.role, am.caption, am.alt_text
            FROM article_media am JOIN media m ON m.id = am.media_id
            WHERE am.article_id = ? ORDER BY am.sort_order
            """,
            (article_id,),
        ).fetchall()

        categories = self.conn.execute(
            "SELECT c.key, c.label, c.icon, ac.is_primary FROM article_category ac "
            "JOIN category c ON c.id = ac.category_id WHERE ac.article_id = ? "
            "ORDER BY ac.is_primary DESC, c.sort_order",
            (article_id,),
        ).fetchall()

        aliases = [
            r["alias"]
            for r in self.conn.execute(
                "SELECT alias FROM article_alias WHERE article_id = ? ORDER BY alias",
                (article_id,),
            ).fetchall()
        ]

        timeline = self.conn.execute(
            "SELECT title, description, start_year, end_year, precision, era, epistemic "
            "FROM timeline_event WHERE article_id = ? ORDER BY start_year",
            (article_id,),
        ).fetchall()

        places = self.conn.execute(
            "SELECT name, kind, lat, lon, country_code, geojson, from_year, to_year "
            "FROM place WHERE article_id = ?",
            (article_id,),
        ).fetchall()
        for place in places:
            if place.get("geojson"):
                place["geojson"] = json.loads(place["geojson"])

        quiz = self.conn.execute(
            "SELECT key, title, age_band, difficulty, "
            "(SELECT COUNT(*) FROM quiz_question q WHERE q.quiz_id = quiz.id) AS question_count "
            "FROM quiz WHERE article_id = ? LIMIT 1",
            (article_id,),
        ).fetchone()

        return {
            "slug": base["slug"],
            "title": base["title"],
            "summary": base["summary"],
            "pronunciation_ipa": base["pronunciation_ipa"],
            "kids_safe": bool(base["kids_safe"]),
            "type": {
                "key": base["type_key"],
                "label": base["type_label"],
                "icon": base["type_icon"],
            },
            "categories": categories,
            "aliases": aliases,
            "reading_level": chosen,
            "requested_level": reading_level,
            "level_substituted": bool(reading_level and chosen and chosen != reading_level),
            "available_levels": levels,
            "content": content,
            "facts": facts,
            "citations": citations,
            "media": media,
            "timeline": timeline,
            "places": places,
            "quiz": quiz,
            "related": self.related(article_id),
            "version": f"{base['version_major']}.{base['version_minor']}"
            if base["version_major"] is not None
            else None,
            "provenance": {
                "origin": base["origin"],
                "revision_created_at": base["revision_created_at"],
                "change_reason": base["change_reason"],
                "reviewed_by": base["reviewed_by"],
                "ai_model": base["ai_model"],
            },
            "quality_score": base["quality_score"],
            "last_reviewed_at": base["last_reviewed_at"],
            "next_review_at": base["next_review_at"],
            "updated_at": base["updated_at"],
        }

    # -- knowledge graph ----------------------------------------------------

    def related(self, article_id: int, limit: int = 24) -> list[dict[str, Any]]:
        """Neighbours in both directions, each labelled with readable wording."""
        outgoing = self.conn.execute(
            """
            SELECT a.slug, a.title, a.summary, r.kind, r.weight, 'out' AS direction,
                   t.icon AS type_icon,
                   (SELECT c.icon FROM article_category ac JOIN category c ON c.id = ac.category_id
                     WHERE ac.article_id = a.id ORDER BY ac.is_primary DESC LIMIT 1) AS icon
            FROM relation r JOIN article a ON a.id = r.to_article_id
            JOIN article_type t ON t.id = a.type_id
            WHERE r.from_article_id = ? AND a.status = 'published'
            """,
            (article_id,),
        ).fetchall()
        incoming = self.conn.execute(
            """
            SELECT a.slug, a.title, a.summary, r.kind, r.weight, 'in' AS direction,
                   t.icon AS type_icon,
                   (SELECT c.icon FROM article_category ac JOIN category c ON c.id = ac.category_id
                     WHERE ac.article_id = a.id ORDER BY ac.is_primary DESC LIMIT 1) AS icon
            FROM relation r JOIN article a ON a.id = r.from_article_id
            JOIN article_type t ON t.id = a.type_id
            WHERE r.to_article_id = ? AND a.status = 'published'
            """,
            (article_id,),
        ).fetchall()

        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in [*outgoing, *incoming]:
            if row["slug"] in seen:
                continue
            seen.add(row["slug"])
            kind = RelationKind(row["kind"])
            row["label"] = (
                RELATION_LABELS[kind] if row["direction"] == "out"
                else INVERSE_RELATION_LABELS[kind]
            )
            out.append(row)
        out.sort(key=lambda r: (-float(r["weight"]), r["title"]))
        return out[:limit]

    def graph(self, slug: str, depth: int = 2, limit: int = 60) -> dict[str, Any]:
        """Breadth-first neighbourhood for the Explore Connections view."""
        root = self.conn.execute(
            "SELECT id, slug, title FROM article WHERE slug = ? AND status = 'published'", (slug,)
        ).fetchone()
        if not root:
            return {"nodes": [], "edges": []}

        nodes: dict[int, dict[str, Any]] = {
            root["id"]: {"id": root["id"], "slug": root["slug"], "title": root["title"],
                         "depth": 0, "icon": None}
        }
        edges: list[dict[str, Any]] = []
        frontier = [root["id"]]

        for level in range(1, depth + 1):
            if not frontier or len(nodes) >= limit:
                break
            placeholders = ",".join("?" * len(frontier))
            rows = self.conn.execute(
                f"""
                SELECT r.from_article_id AS src, r.to_article_id AS dst, r.kind,
                       a1.slug AS src_slug, a2.slug AS dst_slug,
                       a1.title AS src_title, a2.title AS dst_title,
                       (SELECT c.icon FROM article_category ac JOIN category c
                         ON c.id = ac.category_id WHERE ac.article_id = a2.id
                         ORDER BY ac.is_primary DESC LIMIT 1) AS dst_icon,
                       (SELECT c.icon FROM article_category ac JOIN category c
                         ON c.id = ac.category_id WHERE ac.article_id = a1.id
                         ORDER BY ac.is_primary DESC LIMIT 1) AS src_icon
                FROM relation r
                JOIN article a1 ON a1.id = r.from_article_id AND a1.status = 'published'
                JOIN article a2 ON a2.id = r.to_article_id AND a2.status = 'published'
                WHERE r.from_article_id IN ({placeholders})
                   OR r.to_article_id IN ({placeholders})
                """,
                [*frontier, *frontier],
            ).fetchall()

            next_frontier: list[int] = []
            for row in rows:
                for side in ("src", "dst"):
                    node_id = row[side]
                    if node_id not in nodes and len(nodes) < limit:
                        nodes[node_id] = {
                            "id": node_id,
                            "slug": row[f"{side}_slug"],
                            "title": row[f"{side}_title"],
                            "icon": row[f"{side}_icon"],
                            "depth": level,
                        }
                        next_frontier.append(node_id)
                if row["src"] in nodes and row["dst"] in nodes:
                    edge = {
                        "source": row["src"],
                        "target": row["dst"],
                        "kind": row["kind"],
                        "label": RELATION_LABELS[RelationKind(row["kind"])],
                    }
                    if edge not in edges:
                        edges.append(edge)
            frontier = next_frontier

        return {"nodes": list(nodes.values()), "edges": edges, "root": root["slug"]}

    # -- listings -----------------------------------------------------------

    def by_category(
        self, category_key: str, limit: int = 60, offset: int = 0, kids_only: bool = False
    ) -> list[dict[str, Any]]:
        kids = " AND a.kids_safe = 1" if kids_only else ""
        return self.conn.execute(
            f"""
            SELECT a.slug, a.title, a.summary, a.quality_score, t.label AS type_label,
                   t.key AS type_key,
                   (SELECT m.local_path FROM article_media am JOIN media m ON m.id = am.media_id
                     WHERE am.article_id = a.id AND am.role = 'hero' LIMIT 1) AS hero_media,
                   (SELECT group_concat(ic.reading_level) FROM article_content ic
                     WHERE ic.revision_id = a.current_revision_id) AS levels
            FROM article a
            JOIN article_type t ON t.id = a.type_id
            JOIN article_category ac ON ac.article_id = a.id
            JOIN category c ON c.id = ac.category_id
            WHERE c.key = ? AND a.status = 'published'{kids}
            ORDER BY a.title
            LIMIT ? OFFSET ?
            """,
            (category_key, limit, offset),
        ).fetchall()

    def compare(self, slugs: list[str]) -> dict[str, Any]:
        """Side-by-side comparison built from `comparable_key` facts."""
        if not slugs:
            return {"articles": [], "rows": []}
        placeholders = ",".join("?" * len(slugs))
        articles = self.conn.execute(
            f"""
            SELECT a.id, a.slug, a.title, a.summary, a.current_revision_id,
                   t.label AS type_label,
                   (SELECT m.local_path FROM article_media am JOIN media m ON m.id = am.media_id
                     WHERE am.article_id = a.id AND am.role = 'hero' LIMIT 1) AS hero_media
            FROM article a JOIN article_type t ON t.id = a.type_id
            WHERE a.slug IN ({placeholders}) AND a.status = 'published'
            """,
            slugs,
        ).fetchall()
        order = {slug: i for i, slug in enumerate(slugs)}
        articles.sort(key=lambda a: order.get(a["slug"], 99))

        rows: dict[str, dict[str, Any]] = {}
        for art in articles:
            facts = self.conn.execute(
                "SELECT key, label, value_text, value_num, unit, epistemic, comparable_key "
                "FROM fact WHERE revision_id = ? ORDER BY sort_order",
                (art["current_revision_id"],),
            ).fetchall()
            for fact in facts:
                key = fact["comparable_key"] or fact["key"]
                row = rows.setdefault(key, {"key": key, "label": fact["label"], "values": {}})
                row["values"][art["slug"]] = {
                    "text": fact["value_text"],
                    "num": fact["value_num"],
                    "unit": fact["unit"],
                    "epistemic": fact["epistemic"],
                }

        # Only keep dimensions at least two subjects actually share.
        shared = [r for r in rows.values() if len(r["values"]) >= min(2, len(articles))]
        for row in shared:
            nums = [v["num"] for v in row["values"].values() if v["num"] is not None]
            if len(nums) >= 2:
                row["max"] = max(nums)
                row["min"] = min(nums)
        return {"articles": articles, "rows": shared}
