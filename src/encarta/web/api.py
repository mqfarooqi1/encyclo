"""HTTP API.

Every endpoint returns plain JSON and works with the network unplugged. AI-backed
endpoints are the only exception, and they answer with an explicit
``{"available": false, "reason": ...}`` rather than an error or a fabricated
result, so the UI can label the capability honestly.
"""

from __future__ import annotations

import logging

from ..config import Config
from ..db import Database
from ..domain.models import (
    EPISTEMIC_LABELS,
    READING_LEVELS,
    level_description,
    level_label,
)
from ..repositories import ArticleRepository, DiscoveryRepository
from ..services import FactChecker, QualityService, SearchService
from ..services.progress import TrailService
from .app import HttpError, Request, Response, Router, WSGIApp

log = logging.getLogger(__name__)


def create_router(db: Database, config: Config) -> Router:
    router = Router()

    def articles() -> ArticleRepository:
        return ArticleRepository(db.conn)

    def discovery() -> DiscoveryRepository:
        return DiscoveryRepository(db.conn)

    def search_service() -> SearchService:
        return SearchService(db.conn)

    # -- meta ---------------------------------------------------------------

    @router.get("/api/health")
    def health(_: Request) -> Response:
        return Response.json(
            {
                "status": "ok",
                "offline_capable": True,
                "ai_provider": config.ai_provider,
                "network_allowed": config.allow_network,
            }
        )

    @router.get("/api/bootstrap")
    def bootstrap(req: Request) -> Response:
        kids = req.get_bool("kids")
        disco = discovery()
        return Response.json(
            {
                "stats": disco.stats(),
                "categories": disco.categories(kids_only=kids),
                "reading_levels": [
                    {
                        "key": lv.value,
                        "label": level_label(lv),
                        "description": level_description(lv),
                    }
                    for lv in READING_LEVELS
                ],
                "epistemic_labels": {k.value: v for k, v in EPISTEMIC_LABELS.items()},
                "capabilities": {
                    # The UI uses these to label features honestly instead of
                    # showing controls that quietly do nothing.
                    "ai": config.ai_provider != "none",
                    "ai_provider": config.ai_provider,
                    "network": config.allow_network,
                    "semantic_search": False,
                    "maps": True,
                    "timeline": True,
                },
            },
            cache=60,
        )

    # -- discovery ------------------------------------------------------------

    @router.get("/api/home")
    def home(req: Request) -> Response:
        kids = req.get_bool("kids")
        disco = discovery()
        return Response.json(
            {
                "featured": disco.featured(6, kids_only=kids),
                "discovery": disco.daily_discovery(kids_only=kids),
                "did_you_know": disco.did_you_know(5, kids_only=kids),
                "on_this_day": disco.on_this_day(4),
                "recently_updated": disco.recently_updated(6, kids_only=kids),
                "learning_paths": disco.learning_paths(kids_only=kids),
                "categories": disco.categories(kids_only=kids),
                "stats": disco.stats(),
            }
        )

    @router.get("/api/random")
    def random_article(req: Request) -> Response:
        row = discovery().random(req.get("category"), kids_only=req.get_bool("kids"))
        if not row:
            raise HttpError(404, "No articles available")
        return Response.json(row)

    @router.get("/api/categories")
    def categories(req: Request) -> Response:
        return Response.json(discovery().categories(kids_only=req.get_bool("kids")), cache=60)

    @router.get("/api/category/{key}")
    def category(req: Request) -> Response:
        key = req.params["key"]
        limit = req.get_int("limit", 60, high=200)
        offset = req.get_int("offset", 0, high=100_000)
        kids = req.get_bool("kids")
        sort = req.get("sort") or "quality"
        rows = articles().by_category(
            key, limit=limit, offset=offset, kids_only=kids, sort=sort)
        meta = db.one("SELECT key, label, icon, description FROM category WHERE key = ?", (key,))
        if not meta:
            raise HttpError(404, f"Unknown category {key!r}")
        # The real total, not len(rows): a category can hold thousands, and the
        # reader needs to know there is more behind the first page.
        total = articles().count_by_category(key, kids_only=kids)
        return Response.json({
            "category": meta,
            "articles": rows,
            "total": total,
            "offset": offset,
            "limit": limit,
            "sort": sort if sort in ArticleRepository.CATEGORY_ORDERS else "quality",
            "has_more": offset + len(rows) < total,
        })

    # -- search ---------------------------------------------------------------

    @router.get("/api/search")
    def search(req: Request) -> Response:
        query = (req.get("q") or "").strip()
        if not query:
            return Response.json({"query": "", "hits": [], "total": 0})
        if len(query) > 200:
            raise HttpError(400, "Query too long")
        result = search_service().search(
            query,
            limit=req.get_int("limit", 20, high=100),
            offset=req.get_int("offset", 0, high=10_000),
            category=req.get("category"),
            type_key=req.get("type"),
            reading_level=req.get("level"),
            kids_only=req.get_bool("kids"),
        )
        return Response.json(
            {
                "query": result.query,
                "corrected_query": result.corrected_query,
                "expanded_terms": result.expanded_terms,
                "took_ms": result.took_ms,
                "total": result.total,
                "hits": [
                    {
                        "slug": h.slug,
                        "title": h.title,
                        "summary": h.summary,
                        "snippet": h.snippet,
                        "type": h.type_label,
                        "type_key": h.type_key,
                        "category": h.category,
                        "icon": h.category_icon,
                        "score": h.score,
                        "quality_score": h.quality_score,
                        "levels": h.available_levels,
                        "hero_media": h.hero_media,
                    }
                    for h in result.hits
                ],
            }
        )

    @router.get("/api/autocomplete")
    def autocomplete(req: Request) -> Response:
        prefix = (req.get("q") or "").strip()
        if len(prefix) < 2:
            return Response.json([])
        return Response.json(
            search_service().autocomplete(
                prefix, limit=req.get_int("limit", 8, high=20), kids_only=req.get_bool("kids")
            )
        )

    # -- articles --------------------------------------------------------------

    @router.get("/api/article/{slug}")
    def article(req: Request) -> Response:
        repo = articles()
        slug = repo.resolve_slug(req.params["slug"])
        if not slug:
            raise HttpError(404, f"No article {req.params['slug']!r}")
        data = repo.get(slug, req.get("level"))
        if not data:
            raise HttpError(404, f"No article {slug!r}")
        if req.get_bool("kids") and not data["kids_safe"]:
            raise HttpError(403, "This article is not available in Kids Mode")
        return Response.json(data)

    @router.get("/api/article/{slug}/graph")
    def graph(req: Request) -> Response:
        repo = articles()
        slug = repo.resolve_slug(req.params["slug"])
        if not slug:
            raise HttpError(404, "Unknown article")
        return Response.json(
            repo.graph(slug, depth=req.get_int("depth", 2, low=1, high=3),
                       limit=req.get_int("limit", 60, high=200))
        )

    @router.get("/api/article/{slug}/quality")
    def quality(req: Request) -> Response:
        data = QualityService(db.conn).breakdown(req.params["slug"])
        if not data:
            raise HttpError(404, "No quality report for this article")
        return Response.json(data)

    @router.get("/api/article/{slug}/versions")
    def versions(req: Request) -> Response:
        rows = db.query(
            """
            SELECT r.version_major, r.version_minor, r.origin, r.created_at, r.created_by,
                   r.change_reason, r.change_summary, r.reviewed_by, r.ai_model,
                   (r.id = a.current_revision_id) AS is_current
            FROM article_revision r JOIN article a ON a.id = r.article_id
            WHERE a.slug = ?
            ORDER BY r.version_major DESC, r.version_minor DESC
            """,
            (req.params["slug"],),
        )
        if not rows:
            raise HttpError(404, "Unknown article")
        for row in rows:
            row["version"] = f"{row['version_major']}.{row['version_minor']}"
        return Response.json(rows)

    @router.get("/api/compare")
    def compare(req: Request) -> Response:
        slugs = req.get_list("slugs")[:4]
        if len(slugs) < 2:
            raise HttpError(400, "Provide at least two slugs to compare")
        return Response.json(articles().compare(slugs))

    # -- timeline, maps, paths, quizzes -------------------------------------------

    @router.get("/api/timeline")
    def timeline(req: Request) -> Response:
        start = req.get("start")
        end = req.get("end")
        return Response.json(
            discovery().timeline(
                start_year=float(start) if start else None,
                end_year=float(end) if end else None,
                limit=req.get_int("limit", 300, high=2000),
                min_importance=req.get_int("min_importance", 1, low=1, high=5),
            )
        )

    @router.get("/api/places")
    def places(req: Request) -> Response:
        return Response.json(discovery().places(kids_only=req.get_bool("kids")))

    @router.get("/api/paths")
    def paths(req: Request) -> Response:
        return Response.json(discovery().learning_paths(kids_only=req.get_bool("kids")))

    @router.get("/api/path/{key}")
    def path(req: Request) -> Response:
        data = discovery().learning_path(req.params["key"])
        if not data:
            raise HttpError(404, "Unknown learning path")
        return Response.json(data)

    # -- Explorer Trail -----------------------------------------------------------------

    @router.get("/api/trails")
    def trails(req: Request) -> Response:
        return Response.json(TrailService(db.conn).list_trails(kids_only=req.get_bool("kids")))

    @router.get("/api/trail/{key}")
    def trail(req: Request) -> Response:
        data = TrailService(db.conn).get_trail(req.params["key"])
        if not data:
            raise HttpError(404, "Unknown trail")
        return Response.json(data)

    @router.post("/api/trail/{key}/{station}")
    def record_station(req: Request) -> Response:
        payload = req.json()
        try:
            score = int(payload.get("score", 0))
            total = int(payload.get("total", 0))
        except (TypeError, ValueError) as exc:
            raise HttpError(400, "score and total must be whole numbers") from exc
        if total <= 0:
            raise HttpError(400, "total must be greater than zero")
        try:
            result = TrailService(db.conn).record_result(
                req.params["key"], req.params["station"], score, total
            )
        except KeyError as exc:
            raise HttpError(404, str(exc)) from exc
        return Response.json(result, status=201)

    @router.get("/api/badges")
    def badges(_: Request) -> Response:
        return Response.json(TrailService(db.conn).badges())

    @router.delete("/api/progress/trails")
    def reset_progress(req: Request) -> Response:
        TrailService(db.conn).reset(req.get("trail"))
        return Response.json({"ok": True})

    @router.get("/api/quiz/{key}")
    def quiz(req: Request) -> Response:
        quiz_row = db.one(
            "SELECT id, key, title, description, age_band, difficulty FROM quiz WHERE key = ?",
            (req.params["key"],),
        )
        if not quiz_row:
            raise HttpError(404, "Unknown quiz")
        questions = db.query(
            "SELECT id, kind, prompt, explanation, difficulty, "
            "(SELECT slug FROM article WHERE id = quiz_question.article_id) AS article_slug, "
            "(SELECT uid FROM source WHERE id = quiz_question.source_id) AS source_uid "
            "FROM quiz_question WHERE quiz_id = ? ORDER BY sort_order",
            (quiz_row["id"],),
        )
        for question in questions:
            # sort_order carries the answer for ordering questions and match_key
            # for matching ones, so both are needed client-side. Sending answers
            # to the client is fine here: the app is local, single-user and
            # offline, and marking must work with no network round trip.
            question["options"] = db.query(
                "SELECT id, text, is_correct, match_key, sort_order FROM quiz_option "
                "WHERE question_id = ? ORDER BY sort_order",
                (question["id"],),
            )
        quiz_row["questions"] = questions
        return Response.json(quiz_row)

    @router.get("/api/source/{uid}")
    def source(req: Request) -> Response:
        row = db.one("SELECT * FROM source WHERE uid = ?", (req.params["uid"],))
        if not row:
            raise HttpError(404, "Unknown source")
        row["used_by"] = db.query(
            "SELECT DISTINCT a.slug, a.title FROM citation c "
            "JOIN article a ON a.current_revision_id = c.revision_id "
            "WHERE c.source_id = ? ORDER BY a.title LIMIT 50",
            (row["id"],),
        )
        return Response.json(row)

    # -- personalisation (local only) -----------------------------------------------

    @router.get("/api/bookmarks")
    def list_bookmarks(_: Request) -> Response:
        return Response.json(
            db.query(
                "SELECT b.article_slug, b.created_at, b.note, a.title, a.summary "
                "FROM usr.bookmark b LEFT JOIN article a ON a.slug = b.article_slug "
                "ORDER BY b.created_at DESC"
            )
        )

    @router.post("/api/bookmarks")
    def add_bookmark(req: Request) -> Response:
        payload = req.json()
        slug = payload.get("slug")
        if not slug:
            raise HttpError(400, "slug is required")
        with db.transaction():
            db.execute(
                "INSERT INTO usr.bookmark (article_slug, note) VALUES (?, ?) "
                "ON CONFLICT(article_slug) DO UPDATE SET note = excluded.note",
                (slug, payload.get("note")),
            )
        return Response.json({"ok": True, "slug": slug}, status=201)

    @router.delete("/api/bookmarks/{slug}")
    def remove_bookmark(req: Request) -> Response:
        with db.transaction():
            db.execute("DELETE FROM usr.bookmark WHERE article_slug = ?", (req.params["slug"],))
        return Response.json({"ok": True})

    @router.post("/api/progress")
    def save_progress(req: Request) -> Response:
        payload = req.json()
        slug = payload.get("slug")
        if not slug:
            raise HttpError(400, "slug is required")
        with db.transaction():
            db.execute(
                """
                INSERT INTO usr.reading_progress (article_slug, reading_level, scroll_pct,
                                                  last_read_at, read_count)
                VALUES (?, ?, ?, datetime('now'), 1)
                ON CONFLICT(article_slug) DO UPDATE SET
                    reading_level = excluded.reading_level,
                    scroll_pct = MAX(usr.reading_progress.scroll_pct, excluded.scroll_pct),
                    last_read_at = datetime('now'),
                    read_count = usr.reading_progress.read_count + 1
                """,
                (slug, payload.get("level", "adult"), float(payload.get("scroll", 0.0))),
            )
        return Response.json({"ok": True})

    @router.get("/api/continue")
    def continue_reading(_: Request) -> Response:
        return Response.json(
            db.query(
                "SELECT p.article_slug AS slug, p.reading_level, p.scroll_pct, p.last_read_at, "
                "a.title, a.summary FROM usr.reading_progress p "
                "JOIN article a ON a.slug = p.article_slug "
                "WHERE p.is_learned = 0 AND p.scroll_pct < 0.95 "
                "ORDER BY p.last_read_at DESC LIMIT 8"
            )
        )

    # -- AI (optional, always honest about availability) --------------------------------

    @router.post("/api/ask")
    def ask(req: Request) -> Response:
        from ..ai.assistant import EncyclopaediaAssistant

        payload = req.json()
        question = (payload.get("question") or "").strip()
        if not question:
            raise HttpError(400, "question is required")
        assistant = EncyclopaediaAssistant(db.conn, config)
        return Response.json(
            assistant.answer(
                question,
                reading_level=payload.get("level", "adult"),
                kids_mode=bool(payload.get("kids")),
            )
        )

    # -- admin -------------------------------------------------------------------------

    @router.get("/api/admin/dashboard")
    def dashboard(_: Request) -> Response:
        stats = db.one(
            """
            SELECT
              (SELECT COUNT(*) FROM article WHERE status='published')            AS articles,
              (SELECT COUNT(*) FROM article WHERE status='draft')                AS drafts,
              (SELECT COUNT(*) FROM article WHERE next_review_at < date('now')
                 AND status='published')                                         AS needs_review,
              (SELECT COUNT(*) FROM update_proposal WHERE status='pending')      AS proposals,
              (SELECT COUNT(*) FROM source WHERE verification_status='broken')   AS broken_sources,
              (SELECT COUNT(*) FROM source WHERE verification_status='unverified')
                                                                                 AS unverified_sources,
              (SELECT COUNT(*) FROM issue WHERE status='open' AND severity='error') AS errors,
              (SELECT COUNT(*) FROM issue WHERE status='open' AND severity='warning')
                                                                                 AS warnings,
              (SELECT COUNT(*) FROM article WHERE quality_score < 60
                 AND status='published')                                         AS low_quality,
              (SELECT ROUND(AVG(quality_score),1) FROM article WHERE quality_score IS NOT NULL)
                                                                                 AS avg_quality
            """
        )
        return Response.json(
            {
                "stats": stats,
                "packs": db.query(
                    "SELECT key, version, title, article_count, installed_at FROM content_pack "
                    "ORDER BY installed_at DESC"
                ),
                "lowest_quality": db.query(
                    "SELECT slug, title, quality_score FROM article WHERE status='published' "
                    "AND quality_score IS NOT NULL ORDER BY quality_score LIMIT 10"
                ),
                "due_for_review": db.query(
                    "SELECT slug, title, next_review_at FROM article WHERE status='published' "
                    "AND next_review_at IS NOT NULL ORDER BY next_review_at LIMIT 10"
                ),
                "recent_audit": db.query(
                    "SELECT at, actor, action, entity, entity_id FROM audit_log "
                    "ORDER BY at DESC LIMIT 15"
                ),
                # Grouped counts, so a few thousand findings of one routine kind
                # cannot bury a handful of errors of another.
                "issue_kinds": db.query(
                    "SELECT kind, severity, COUNT(*) AS n FROM issue WHERE status = 'open' "
                    "GROUP BY kind, severity "
                    "ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 "
                    "ELSE 2 END, n DESC"
                ),
            }
        )

    @router.get("/api/admin/issues")
    def issues(req: Request) -> Response:
        severity = req.get("severity")
        # Qualified: `issue` and `article` both have status/severity-shaped
        # columns, and an unqualified name is ambiguous once they are joined.
        clause, params = "i.status = 'open'", []
        if severity in ("info", "warning", "error"):
            clause += " AND i.severity = ?"
            params.append(severity)
        return Response.json(
            db.query(
                f"""
                SELECT i.id, i.kind, i.severity, i.detail, i.detected_at,
                       a.slug, a.title, s.uid AS source_uid
                FROM issue i
                LEFT JOIN article a ON a.id = i.article_id
                LEFT JOIN source s ON s.id = i.source_id
                WHERE {clause}
                ORDER BY CASE i.severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                         i.detected_at DESC
                LIMIT ?
                """,
                (*params, req.get_int("limit", 100, high=500)),
            )
        )

    @router.get("/api/admin/proposals")
    def proposals(_: Request) -> Response:
        return Response.json(
            db.query(
                "SELECT p.id, p.status, p.origin, p.ai_model, p.created_at, p.rationale, "
                "p.confidence, p.diff_json, a.slug, a.title FROM update_proposal p "
                "JOIN article a ON a.id = p.article_id WHERE p.status = 'pending' "
                "ORDER BY p.created_at DESC LIMIT 100"
            )
        )

    @router.post("/api/admin/factcheck")
    def run_factcheck(_: Request) -> Response:
        return Response.json(FactChecker(db.conn).run())

    return router


def create_app(config: Config | None = None, db: Database | None = None) -> WSGIApp:
    cfg = config or Config.load()
    database = db or Database(cfg.content_db, cfg.user_db)
    return WSGIApp(create_router(database, cfg))
