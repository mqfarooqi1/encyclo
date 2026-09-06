"""Content pack loader.

Reads a pack directory, validates every article, and ingests it into the
content database. The loader is *version-aware and idempotent*: re-loading an
unchanged pack is a no-op, while a changed article creates a new revision and
repoints the article at it. Nothing is ever edited in place.

Pack layout::

    <pack>/
      pack.json         key, version, title, description
      taxonomy.json     article types and categories
      sources.json      the evidence catalogue
      media.json        media catalogue with licence metadata
      articles/*.json   one file per article
      quizzes.json      optional
      paths.json        optional learning paths
      timeline.json     optional standalone timeline events
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ..domain.models import READING_LEVELS, ReadingLevel
from .validate import ContentValidator, Finding, has_errors

log = logging.getLogger(__name__)

# Words per minute used for the "4 min read" estimate, tuned per audience.
WPM = {
    ReadingLevel.AGE_6_8.value: 90,
    ReadingLevel.AGE_9_12.value: 140,
    ReadingLevel.TEEN.value: 200,
    ReadingLevel.ADULT.value: 240,
}


class LoaderError(RuntimeError):
    """Raised when a pack cannot be loaded."""


@dataclass(slots=True)
class LoadReport:
    pack_key: str = ""
    pack_version: str = ""
    articles_created: int = 0
    articles_revised: int = 0
    articles_unchanged: int = 0
    sources: int = 0
    media: int = 0
    relations: int = 0
    timeline_events: int = 0
    places: int = 0
    quizzes: int = 0
    paths: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def total_articles(self) -> int:
        return self.articles_created + self.articles_revised + self.articles_unchanged

    def summary(self) -> str:
        return (
            f"{self.pack_key} {self.pack_version}: "
            f"{self.articles_created} new, {self.articles_revised} revised, "
            f"{self.articles_unchanged} unchanged | "
            f"{self.sources} sources, {self.media} media, {self.relations} relations, "
            f"{self.timeline_events} events, {self.quizzes} quizzes, {self.paths} paths"
        )


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        if default is not None:
            return default
        raise LoaderError(f"required file missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoaderError(f"{path.name} is not valid JSON: {exc}") from exc


def _content_hash(article: dict[str, Any]) -> str:
    """Stable hash of the parts of an article that constitute its text.

    Deliberately excludes bookkeeping such as review dates, so re-loading a pack
    whose only change is a review timestamp does not manufacture a revision.
    """
    payload = {
        k: article.get(k)
        for k in ("title", "summary", "content", "facts", "citations", "media", "aliases")
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class PackLoader:
    def __init__(self, conn: sqlite3.Connection, *, strict: bool = True) -> None:
        self.conn = conn
        self.strict = strict

    # -- taxonomy ---------------------------------------------------------

    def _load_taxonomy(self, taxonomy: dict[str, Any]) -> None:
        for item in taxonomy.get("types", []):
            self.conn.execute(
                "INSERT INTO article_type (key, label, icon, fact_schema, default_review_months) "
                "VALUES (:key, :label, :icon, :fact_schema, :months) "
                "ON CONFLICT(key) DO UPDATE SET label=excluded.label, icon=excluded.icon, "
                "fact_schema=excluded.fact_schema, "
                "default_review_months=excluded.default_review_months",
                {
                    "key": item["key"],
                    "label": item["label"],
                    "icon": item.get("icon"),
                    "fact_schema": json.dumps(item.get("fact_schema", [])),
                    "months": int(item.get("review_months", 36)),
                },
            )
        # Two passes so a child category may reference a parent defined later.
        for item in taxonomy.get("categories", []):
            self.conn.execute(
                "INSERT INTO category (key, label, icon, description, sort_order, kids_safe) "
                "VALUES (:key, :label, :icon, :description, :sort_order, :kids_safe) "
                "ON CONFLICT(key) DO UPDATE SET label=excluded.label, icon=excluded.icon, "
                "description=excluded.description, sort_order=excluded.sort_order, "
                "kids_safe=excluded.kids_safe",
                {
                    "key": item["key"],
                    "label": item["label"],
                    "icon": item.get("icon"),
                    "description": item.get("description", ""),
                    "sort_order": int(item.get("sort_order", 0)),
                    "kids_safe": 1 if item.get("kids_safe", True) else 0,
                },
            )
        for item in taxonomy.get("categories", []):
            if item.get("parent"):
                self.conn.execute(
                    "UPDATE category SET parent_id = (SELECT id FROM category WHERE key = ?) "
                    "WHERE key = ?",
                    (item["parent"], item["key"]),
                )
        for item in taxonomy.get("review_policies", []):
            self.conn.execute(
                "INSERT INTO review_policy (scope, scope_key, review_months, rationale) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(scope, scope_key) DO UPDATE SET "
                "review_months=excluded.review_months, rationale=excluded.rationale",
                (
                    item["scope"],
                    item["key"],
                    int(item["review_months"]),
                    item.get("rationale", ""),
                ),
            )

    # -- sources and media -------------------------------------------------

    def _load_sources(self, sources: list[dict[str, Any]]) -> int:
        for src in sources:
            self.conn.execute(
                """
                INSERT INTO source (uid, title, publisher, authors, source_type, url, doi, isbn,
                                    published_date, accessed_date, tier, license, license_url, notes)
                VALUES (:uid, :title, :publisher, :authors, :source_type, :url, :doi, :isbn,
                        :published_date, :accessed_date, :tier, :license, :license_url, :notes)
                ON CONFLICT(uid) DO UPDATE SET
                    title=excluded.title, publisher=excluded.publisher, authors=excluded.authors,
                    source_type=excluded.source_type, url=excluded.url, doi=excluded.doi,
                    isbn=excluded.isbn, published_date=excluded.published_date,
                    accessed_date=excluded.accessed_date, tier=excluded.tier,
                    license=excluded.license, license_url=excluded.license_url, notes=excluded.notes
                """,
                {
                    "uid": src["uid"],
                    "title": src["title"],
                    "publisher": src["publisher"],
                    "authors": src.get("authors"),
                    "source_type": src.get("type", "web"),
                    "url": src.get("url"),
                    "doi": src.get("doi"),
                    "isbn": src.get("isbn"),
                    "published_date": src.get("published"),
                    "accessed_date": src.get("accessed"),
                    "tier": int(src.get("tier", 4)),
                    "license": src.get("license"),
                    "license_url": src.get("license_url"),
                    "notes": src.get("notes"),
                },
            )
        return len(sources)

    def _load_media(self, media: list[dict[str, Any]]) -> int:
        for item in media:
            redistributable = 1 if item.get("redistributable") else 0
            self.conn.execute(
                """
                INSERT INTO media (uid, kind, title, description, creator, credit_line, license,
                                   license_url, source_url, accessed_date, provenance,
                                   is_redistributable, local_path, sha256, mime, width, height)
                VALUES (:uid, :kind, :title, :description, :creator, :credit_line, :license,
                        :license_url, :source_url, :accessed_date, :provenance,
                        :redistributable, :local_path, :sha256, :mime, :width, :height)
                ON CONFLICT(uid) DO UPDATE SET
                    kind=excluded.kind, title=excluded.title, description=excluded.description,
                    creator=excluded.creator, credit_line=excluded.credit_line,
                    license=excluded.license, license_url=excluded.license_url,
                    source_url=excluded.source_url, provenance=excluded.provenance,
                    is_redistributable=excluded.is_redistributable
                """,
                {
                    "uid": item["uid"],
                    "kind": item.get("kind", "image"),
                    "title": item["title"],
                    "description": item.get("description"),
                    "creator": item.get("creator"),
                    "credit_line": item["credit"],
                    "license": item["license"],
                    "license_url": item.get("license_url"),
                    "source_url": item.get("source_url"),
                    "accessed_date": item.get("accessed"),
                    "provenance": item.get("provenance", "third_party"),
                    "redistributable": redistributable,
                    "local_path": item.get("local_path"),
                    "sha256": item.get("sha256"),
                    "mime": item.get("mime"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                },
            )
        return len(media)

    # -- articles -----------------------------------------------------------

    def _upsert_article_shell(self, art: dict[str, Any]) -> int:
        type_id = self.conn.execute(
            "SELECT id FROM article_type WHERE key = ?", (art["type"],)
        ).fetchone()
        if not type_id:
            raise LoaderError(f"{art['slug']}: unknown article type {art['type']!r}")

        levels = set(art.get("content", {}))
        min_level = next((lv.value for lv in READING_LEVELS if lv.value in levels), None)

        self.conn.execute(
            """
            INSERT INTO article (slug, title, type_id, summary, status, pronunciation_ipa,
                                 min_reading_level, kids_safe)
            VALUES (:slug, :title, :type_id, :summary, :status, :ipa, :min_level, :kids_safe)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title, type_id=excluded.type_id, summary=excluded.summary,
                status=excluded.status, pronunciation_ipa=excluded.pronunciation_ipa,
                min_reading_level=excluded.min_reading_level, kids_safe=excluded.kids_safe,
                updated_at=datetime('now')
            """,
            {
                "slug": art["slug"],
                "title": art["title"],
                "type_id": type_id["id"],
                "summary": art.get("summary", ""),
                "status": art.get("status", "published"),
                "ipa": art.get("pronunciation_ipa"),
                "min_level": min_level,
                "kids_safe": 1 if art.get("kids_safe", True) else 0,
            },
        )
        row = self.conn.execute("SELECT id FROM article WHERE slug = ?", (art["slug"],)).fetchone()
        article_id = int(row["id"])

        self.conn.execute("DELETE FROM article_alias WHERE article_id = ?", (article_id,))
        for alias in art.get("aliases", []):
            text, kind = (alias, "alternative") if isinstance(alias, str) else (
                alias["text"],
                alias.get("kind", "alternative"),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO article_alias (article_id, alias, kind) VALUES (?, ?, ?)",
                (article_id, text, kind),
            )

        self.conn.execute("DELETE FROM article_category WHERE article_id = ?", (article_id,))
        primary = art.get("primary_category")
        for cat in art.get("categories", []):
            cat_row = self.conn.execute(
                "SELECT id FROM category WHERE key = ?", (cat,)
            ).fetchone()
            if not cat_row:
                raise LoaderError(f"{art['slug']}: unknown category {cat!r}")
            self.conn.execute(
                "INSERT OR IGNORE INTO article_category (article_id, category_id, is_primary) "
                "VALUES (?, ?, ?)",
                (article_id, cat_row["id"], 1 if cat == primary else 0),
            )
        return article_id

    def _create_revision(self, article_id: int, art: dict[str, Any], digest: str) -> int:
        prev = self.conn.execute(
            "SELECT id, version_major, version_minor FROM article_revision "
            "WHERE article_id = ? ORDER BY version_major DESC, version_minor DESC LIMIT 1",
            (article_id,),
        ).fetchone()
        if prev:
            major, minor = int(prev["version_major"]), int(prev["version_minor"]) + 1
            parent = prev["id"]
            reason = art.get("change_reason", "Content updated from pack")
        else:
            major, minor, parent = 1, 0, None
            reason = art.get("change_reason", "Initial import")

        cur = self.conn.execute(
            """
            INSERT INTO article_revision (article_id, version_major, version_minor,
                parent_revision_id, origin, created_by, change_reason, change_summary,
                content_hash)
            VALUES (?, ?, ?, ?, 'import', ?, ?, ?, ?)
            """,
            (
                article_id,
                major,
                minor,
                parent,
                art.get("author", "content-pack"),
                reason,
                art.get("change_summary", ""),
                digest,
            ),
        )
        revision_id = int(cur.lastrowid or 0)

        for level, block in art.get("content", {}).items():
            body = block.get("body", "")
            words = len(body.split())
            self.conn.execute(
                """
                INSERT INTO article_content (revision_id, reading_level, summary, body_md,
                                             word_count, reading_time_min)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    level,
                    block.get("summary", ""),
                    body,
                    words,
                    max(1, round(words / WPM.get(level, 200))),
                ),
            )

        fact_ids: dict[str, int] = {}
        for order, fact in enumerate(art.get("facts", [])):
            value = fact.get("value")
            cur = self.conn.execute(
                """
                INSERT INTO fact (revision_id, key, label, value_text, value_num, unit,
                                  epistemic, confidence, group_label, sort_order, comparable_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    fact["key"],
                    fact["label"],
                    str(value),
                    fact.get("value_num"),
                    fact.get("unit"),
                    fact.get("epistemic", "fact"),
                    fact.get("confidence"),
                    fact.get("group"),
                    order,
                    fact.get("comparable_key"),
                ),
            )
            fact_ids[fact["key"]] = int(cur.lastrowid or 0)

        citation_ids: dict[int, int] = {}
        for cit in art.get("citations", []):
            src = self.conn.execute(
                "SELECT id FROM source WHERE uid = ?", (cit["source"],)
            ).fetchone()
            if not src:
                raise LoaderError(
                    f"{art['slug']}: citation references unknown source {cit['source']!r}"
                )
            cur = self.conn.execute(
                """
                INSERT INTO citation (revision_id, source_id, marker, claim, locator, quote,
                                      supports)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    src["id"],
                    cit["marker"],
                    cit["claim"],
                    cit.get("locator"),
                    cit.get("quote"),
                    cit.get("supports", "supports"),
                ),
            )
            citation_ids[int(cit["marker"])] = int(cur.lastrowid or 0)

        # Link facts to the citations that support them. Authors declare this on
        # the fact ("cite": [1, 3]), which is the direction people actually think
        # in when writing a quick-facts panel.
        for fact in art.get("facts", []):
            fact_id = fact_ids.get(fact.get("key", ""))
            if fact_id is None:
                continue
            for marker in fact.get("cite", []):
                citation_id = citation_ids.get(int(marker))
                if citation_id is None:
                    raise LoaderError(
                        f"{art['slug']}: fact {fact['key']!r} cites [{marker}], "
                        "which is not a defined citation"
                    )
                self.conn.execute(
                    "INSERT OR IGNORE INTO fact_citation (fact_id, citation_id) VALUES (?, ?)",
                    (fact_id, citation_id),
                )

        self.conn.execute(
            "UPDATE article SET current_revision_id = ?, updated_at = datetime('now') WHERE id = ?",
            (revision_id, article_id),
        )
        self.conn.execute(
            "INSERT INTO audit_log (actor, action, entity, entity_id, detail) VALUES (?,?,?,?,?)",
            (
                "content-pack",
                "revision.created",
                "article",
                str(article_id),
                json.dumps({"version": f"{major}.{minor}", "hash": digest[:12]}),
            ),
        )
        return revision_id

    def _apply_review_dates(self, article_id: int, art: dict[str, Any], type_key: str) -> None:
        review = art.get("review", {})
        last = review.get("last_reviewed") or date.today().isoformat()
        months = review.get("review_months")
        if months is None:
            row = self.conn.execute(
                "SELECT review_months FROM review_policy WHERE scope='type' AND scope_key=?",
                (type_key,),
            ).fetchone()
            if row:
                months = int(row["review_months"])
        if months is None:
            row = self.conn.execute(
                "SELECT default_review_months FROM article_type WHERE key = ?", (type_key,)
            ).fetchone()
            months = int(row["default_review_months"]) if row else 36
        self.conn.execute(
            "UPDATE article SET last_reviewed_at = ?, "
            "next_review_at = date(?, ?) WHERE id = ?",
            (last, last, f"+{int(months)} months", article_id),
        )

    def _load_media_links(self, article_id: int, art: dict[str, Any]) -> None:
        self.conn.execute("DELETE FROM article_media WHERE article_id = ?", (article_id,))
        for order, item in enumerate(art.get("media", [])):
            row = self.conn.execute(
                "SELECT id FROM media WHERE uid = ?", (item["uid"],)
            ).fetchone()
            if not row:
                raise LoaderError(f"{art['slug']}: unknown media {item['uid']!r}")
            self.conn.execute(
                "INSERT OR REPLACE INTO article_media "
                "(article_id, media_id, role, caption, alt_text, sort_order) VALUES (?,?,?,?,?,?)",
                (
                    article_id,
                    row["id"],
                    item.get("role", "inline"),
                    item.get("caption"),
                    item.get("alt", ""),
                    order,
                ),
            )

    def _load_relations(self, articles: list[dict[str, Any]]) -> int:
        count = 0
        for art in articles:
            src = self.conn.execute(
                "SELECT id FROM article WHERE slug = ?", (art["slug"],)
            ).fetchone()
            if not src:
                continue
            self.conn.execute("DELETE FROM relation WHERE from_article_id = ?", (src["id"],))
            for rel in art.get("relations", []):
                dst = self.conn.execute(
                    "SELECT id FROM article WHERE slug = ?", (rel["to"],)
                ).fetchone()
                if not dst:
                    self.conn.execute(
                        "INSERT INTO issue (article_id, kind, severity, detail) VALUES (?,?,?,?)",
                        (
                            src["id"],
                            "orphan_relation",
                            "warning",
                            f"relation targets missing article {rel['to']!r}",
                        ),
                    )
                    continue
                self.conn.execute(
                    "INSERT OR IGNORE INTO relation (from_article_id, to_article_id, kind, "
                    "weight, note) VALUES (?,?,?,?,?)",
                    (
                        src["id"],
                        dst["id"],
                        rel.get("kind", "related"),
                        float(rel.get("weight", 1.0)),
                        rel.get("note"),
                    ),
                )
                count += 1
        return count

    def _load_timeline_and_places(self, articles: list[dict[str, Any]]) -> tuple[int, int]:
        events = places = 0
        for art in articles:
            row = self.conn.execute(
                "SELECT id FROM article WHERE slug = ?", (art["slug"],)
            ).fetchone()
            if not row:
                continue
            article_id = row["id"]
            self.conn.execute("DELETE FROM timeline_event WHERE article_id = ?", (article_id,))
            for ev in art.get("timeline", []):
                self.conn.execute(
                    """
                    INSERT INTO timeline_event (article_id, title, description, start_year,
                        end_year, precision, era, importance, epistemic)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        article_id,
                        ev["title"],
                        ev.get("description", ""),
                        float(ev["start"]),
                        float(ev["end"]) if ev.get("end") is not None else None,
                        ev.get("precision", "exact"),
                        ev.get("era"),
                        int(ev.get("importance", 3)),
                        ev.get("epistemic", "fact"),
                    ),
                )
                events += 1

            self.conn.execute("DELETE FROM place WHERE article_id = ?", (article_id,))
            for pl in art.get("places", []):
                cur = self.conn.execute(
                    """
                    INSERT INTO place (article_id, name, kind, lat, lon, country_code, geojson,
                                       dataset_uid, from_year, to_year)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        article_id,
                        pl["name"],
                        pl.get("kind", "point"),
                        pl.get("lat"),
                        pl.get("lon"),
                        pl.get("country"),
                        json.dumps(pl["geojson"]) if pl.get("geojson") else None,
                        pl.get("dataset"),
                        pl.get("from_year"),
                        pl.get("to_year"),
                    ),
                )
                place_id = int(cur.lastrowid or 0)
                if pl.get("lat") is not None and pl.get("lon") is not None:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO place_bbox VALUES (?,?,?,?,?)",
                        (place_id, pl["lat"], pl["lat"], pl["lon"], pl["lon"]),
                    )
                places += 1
        return events, places

    # -- public API -----------------------------------------------------------

    def load_pack(self, pack_dir: Path) -> LoadReport:
        pack_dir = Path(pack_dir)
        meta = _read_json(pack_dir / "pack.json")
        taxonomy = _read_json(pack_dir / "taxonomy.json", {})
        sources = _read_json(pack_dir / "sources.json", [])
        media = _read_json(pack_dir / "media.json", [])

        article_files = sorted((pack_dir / "articles").glob("*.json"))
        articles = [_read_json(p) for p in article_files]
        if not articles:
            raise LoaderError(f"pack {pack_dir} contains no articles")

        report = LoadReport(pack_key=meta["key"], pack_version=meta["version"])

        validator = ContentValidator(
            known_sources={s["uid"] for s in sources},
            known_media={m["uid"] for m in media},
            known_slugs={a.get("slug", "") for a in articles},
            known_types={t["key"] for t in taxonomy.get("types", [])},
            known_categories={c["key"] for c in taxonomy.get("categories", [])},
        )
        for path, art in zip(article_files, articles, strict=True):
            report.findings.extend(validator.validate_article(art, where=path.name))

        if has_errors(report.findings) and self.strict:
            errors = [f for f in report.findings if f.severity == "error"]
            detail = "\n  ".join(str(f) for f in errors[:20])
            raise LoaderError(
                f"{len(errors)} validation error(s); refusing to load:\n  {detail}"
            )

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._load_taxonomy(taxonomy)
            report.sources = self._load_sources(sources)
            report.media = self._load_media(media)

            for art in articles:
                article_id = self._upsert_article_shell(art)
                digest = _content_hash(art)
                existing = self.conn.execute(
                    "SELECT content_hash FROM article_revision WHERE article_id = ? "
                    "ORDER BY version_major DESC, version_minor DESC LIMIT 1",
                    (article_id,),
                ).fetchone()
                if existing and existing["content_hash"] == digest:
                    report.articles_unchanged += 1
                else:
                    self._create_revision(article_id, art, digest)
                    if existing:
                        report.articles_revised += 1
                    else:
                        report.articles_created += 1
                self._load_media_links(article_id, art)
                self._apply_review_dates(article_id, art, art["type"])

            report.relations = self._load_relations(articles)
            report.timeline_events, report.places = self._load_timeline_and_places(articles)
            report.quizzes = self._load_quizzes(_read_json(pack_dir / "quizzes.json", []))
            report.paths = self._load_paths(_read_json(pack_dir / "paths.json", []))
            self._load_synonyms(_read_json(pack_dir / "synonyms.json", []))

            # Persist non-fatal findings as reviewable issues.
            for finding in report.findings:
                if finding.severity == "info":
                    continue
                row = self.conn.execute(
                    "SELECT id FROM article WHERE slug = ?",
                    (Path(finding.where).stem,),
                ).fetchone()
                self.conn.execute(
                    "INSERT INTO issue (article_id, kind, severity, detail) VALUES (?,?,?,?)",
                    (
                        row["id"] if row else None,
                        finding.kind if finding.kind in _ISSUE_KINDS else "low_quality",
                        finding.severity,
                        finding.message,
                    ),
                )

            cur = self.conn.execute(
                "INSERT INTO content_pack (key, version, title, description, article_count) "
                "VALUES (?,?,?,?,?) ON CONFLICT(key, version) DO UPDATE SET "
                "article_count=excluded.article_count, installed_at=datetime('now')",
                (
                    meta["key"],
                    meta["version"],
                    meta.get("title", meta["key"]),
                    meta.get("description", ""),
                    len(articles),
                ),
            )
            pack_row = self.conn.execute(
                "SELECT id FROM content_pack WHERE key = ? AND version = ?",
                (meta["key"], meta["version"]),
            ).fetchone()
            for art in articles:
                arow = self.conn.execute(
                    "SELECT id FROM article WHERE slug = ?", (art["slug"],)
                ).fetchone()
                if arow:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO pack_article (pack_id, article_id) VALUES (?,?)",
                        (pack_row["id"], arow["id"]),
                    )
            del cur
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()
        return report

    def _load_quizzes(self, quizzes: list[dict[str, Any]]) -> int:
        for quiz in quizzes:
            article_id = None
            if quiz.get("article"):
                row = self.conn.execute(
                    "SELECT id FROM article WHERE slug = ?", (quiz["article"],)
                ).fetchone()
                article_id = row["id"] if row else None
            category_id = None
            if quiz.get("category"):
                row = self.conn.execute(
                    "SELECT id FROM category WHERE key = ?", (quiz["category"],)
                ).fetchone()
                category_id = row["id"] if row else None
            self.conn.execute(
                "INSERT INTO quiz (key, title, description, article_id, category_id, age_band, "
                "difficulty) VALUES (?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "title=excluded.title, description=excluded.description",
                (
                    quiz["key"],
                    quiz["title"],
                    quiz.get("description", ""),
                    article_id,
                    category_id,
                    quiz.get("age_band", "age9_12"),
                    quiz.get("difficulty", "medium"),
                ),
            )
            qrow = self.conn.execute(
                "SELECT id FROM quiz WHERE key = ?", (quiz["key"],)
            ).fetchone()
            self.conn.execute("DELETE FROM quiz_question WHERE quiz_id = ?", (qrow["id"],))
            for order, question in enumerate(quiz.get("questions", [])):
                art_row = None
                if question.get("article"):
                    art_row = self.conn.execute(
                        "SELECT id FROM article WHERE slug = ?", (question["article"],)
                    ).fetchone()
                src_row = None
                if question.get("source"):
                    src_row = self.conn.execute(
                        "SELECT id FROM source WHERE uid = ?", (question["source"],)
                    ).fetchone()
                cur = self.conn.execute(
                    "INSERT INTO quiz_question (quiz_id, kind, prompt, explanation, difficulty, "
                    "article_id, source_id, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        qrow["id"],
                        question.get("kind", "multiple_choice"),
                        question["prompt"],
                        question["explanation"],
                        question.get("difficulty", quiz.get("difficulty", "medium")),
                        art_row["id"] if art_row else None,
                        src_row["id"] if src_row else None,
                        order,
                    ),
                )
                question_id = int(cur.lastrowid or 0)
                for opt_order, option in enumerate(question.get("options", [])):
                    self.conn.execute(
                        "INSERT INTO quiz_option (question_id, text, is_correct, sort_order) "
                        "VALUES (?,?,?,?)",
                        (
                            question_id,
                            option["text"],
                            1 if option.get("correct") else 0,
                            opt_order,
                        ),
                    )
        return len(quizzes)

    def _load_synonyms(self, synonyms: list[dict[str, Any]]) -> int:
        """Query-expansion terms, so a reader can find an article without knowing
        its exact title ('largest dinosaur', 'red planet', 'cavemen')."""
        for syn in synonyms:
            self.conn.execute(
                "INSERT OR IGNORE INTO synonym (term, expands_to, weight) VALUES (?, ?, ?)",
                (syn["term"].lower(), syn["expands_to"].lower(), float(syn.get("weight", 0.8))),
            )
        return len(synonyms)

    def _load_paths(self, paths: list[dict[str, Any]]) -> int:
        for path in paths:
            self.conn.execute(
                "INSERT INTO learning_path (key, title, description, icon, age_band) "
                "VALUES (?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET title=excluded.title, "
                "description=excluded.description, icon=excluded.icon",
                (
                    path["key"],
                    path["title"],
                    path.get("description", ""),
                    path.get("icon"),
                    path.get("age_band", "age9_12"),
                ),
            )
            prow = self.conn.execute(
                "SELECT id FROM learning_path WHERE key = ?", (path["key"],)
            ).fetchone()
            self.conn.execute("DELETE FROM learning_path_step WHERE path_id = ?", (prow["id"],))
            order = 0
            for slug in path.get("steps", []):
                arow = self.conn.execute(
                    "SELECT id FROM article WHERE slug = ?", (slug,)
                ).fetchone()
                if not arow:
                    continue
                self.conn.execute(
                    "INSERT INTO learning_path_step (path_id, article_id, sort_order) "
                    "VALUES (?,?,?)",
                    (prow["id"], arow["id"], order),
                )
                order += 1
        return len(paths)


_ISSUE_KINDS = {
    "missing_citation", "broken_source", "unsupported_claim", "outdated", "contradiction",
    "duplicate_article", "suspicious_statistic", "inconsistent_unit", "inconsistent_name",
    "orphan_relation", "missing_reading_level", "missing_alt_text", "low_quality",
}
