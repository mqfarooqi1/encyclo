"""Quality scoring and the automated fact checker."""

from __future__ import annotations

from datetime import date, timedelta

from encarta.services.quality import FactChecker, QualityService


def test_every_article_is_scored(conn):
    unscored = conn.execute(
        "SELECT slug FROM article WHERE status='published' AND quality_score IS NULL"
    ).fetchall()
    assert not unscored


def test_scores_are_in_range(conn):
    rows = conn.execute(
        "SELECT slug, quality_score FROM article WHERE quality_score IS NOT NULL"
    ).fetchall()
    for row in rows:
        assert 0 <= row["quality_score"] <= 100, row["slug"]


def test_breakdown_components_sum_to_the_total(conn):
    service = QualityService(conn)
    article_id = conn.execute("SELECT id FROM article WHERE slug='earth'").fetchone()["id"]
    breakdown = service.score_article(article_id)
    assert breakdown is not None
    assert breakdown.total() == service.breakdown("earth")["total"]


def test_freshness_never_collapses_for_an_old_article():
    """An article is not wrong because it is old; it is only due for review."""
    long_overdue = (date.today() - timedelta(days=365 * 8)).isoformat()
    assert QualityService._freshness(long_overdue) >= 40
    assert QualityService._freshness((date.today() + timedelta(days=30)).isoformat()) == 100


def test_fact_checker_finds_no_issues_in_the_shipped_pack(conn):
    counts = FactChecker(conn).run()
    assert sum(counts.values()) == 0, counts


def test_fact_checker_detects_a_missing_citation(conn):
    """Remove the evidence and the checker must notice."""
    revision = conn.execute(
        "SELECT current_revision_id AS r FROM article WHERE slug='volcano'"
    ).fetchone()["r"]
    saved = conn.execute(
        "SELECT source_id, marker, claim, supports FROM citation WHERE revision_id=?",
        (revision,),
    ).fetchall()
    conn.execute("DELETE FROM citation WHERE revision_id=?", (revision,))
    conn.commit()
    try:
        counts = FactChecker(conn).run()
        assert counts["missing_citation"] >= 1
    finally:
        for row in saved:
            conn.execute(
                "INSERT INTO citation (revision_id, source_id, marker, claim, supports) "
                "VALUES (?,?,?,?,?)",
                (revision, row["source_id"], row["marker"], row["claim"], row["supports"]),
            )
        conn.commit()
        FactChecker(conn).run()


def test_unit_check_ignores_superseded_revisions(conn):
    """Append-only history must not produce permanent false positives."""
    revision = conn.execute(
        "SELECT current_revision_id AS r FROM article WHERE slug='mars'"
    ).fetchone()["r"]
    # An orphaned revision carrying a conflicting unit, as a superseded one would.
    cursor = conn.execute(
        "INSERT INTO article_revision (article_id, version_major, version_minor, origin, "
        "created_by) SELECT article_id, 99, 0, 'import', 'test' FROM article_revision WHERE id=?",
        (revision,),
    )
    conn.execute(
        "INSERT INTO fact (revision_id, key, label, value_text, unit, comparable_key) "
        "VALUES (?, 'old_diameter', 'Diameter', '6779', 'miles', 'diameter')",
        (cursor.lastrowid,),
    )
    conn.commit()
    try:
        counts = FactChecker(conn).run()
        assert counts["inconsistent_unit"] == 0
    finally:
        conn.execute("DELETE FROM article_revision WHERE id=?", (cursor.lastrowid,))
        conn.commit()


def test_shared_comparable_keys_use_one_unit(conn):
    conflicts = conn.execute(
        "SELECT f.comparable_key FROM fact f "
        "JOIN article a ON a.current_revision_id = f.revision_id "
        "WHERE f.comparable_key IS NOT NULL GROUP BY f.comparable_key "
        "HAVING COUNT(DISTINCT COALESCE(f.unit,'')) > 1"
    ).fetchall()
    assert not conflicts, [r["comparable_key"] for r in conflicts]
