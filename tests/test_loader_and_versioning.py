"""Loading content, and the version/provenance guarantees around it."""

from __future__ import annotations

import json

import pytest

from encarta.content.loader import LoaderError, PackLoader


def test_pack_loads(conn):
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM article WHERE status='published'"
    ).fetchone()["n"] >= 15
    assert conn.execute("SELECT COUNT(*) AS n FROM source").fetchone()["n"] > 20


def test_every_published_article_has_a_current_revision(conn):
    orphans = conn.execute(
        "SELECT slug FROM article WHERE status='published' AND current_revision_id IS NULL"
    ).fetchall()
    assert not orphans


def test_every_published_article_cites_at_least_one_source(conn):
    """The core promise of the product, asserted against real data."""
    uncited = conn.execute(
        "SELECT a.slug FROM article a WHERE a.status='published' AND NOT EXISTS "
        "(SELECT 1 FROM citation c WHERE c.revision_id = a.current_revision_id)"
    ).fetchall()
    assert not uncited, [r["slug"] for r in uncited]


def test_every_article_has_an_adult_level(conn):
    missing = conn.execute(
        "SELECT a.slug FROM article a WHERE a.status='published' AND NOT EXISTS "
        "(SELECT 1 FROM article_content ic WHERE ic.revision_id = a.current_revision_id "
        " AND ic.reading_level='adult')"
    ).fetchall()
    assert not missing, [r["slug"] for r in missing]


def test_facts_marked_as_established_are_cited(conn):
    """Anything shown to a reader as settled fact must be traceable."""
    uncited = conn.execute(
        "SELECT a.slug, f.key FROM fact f "
        "JOIN article a ON a.current_revision_id = f.revision_id "
        "WHERE f.epistemic = 'fact' AND NOT EXISTS "
        "(SELECT 1 FROM fact_citation fc WHERE fc.fact_id = f.id)"
    ).fetchall()
    assert not uncited, [(r["slug"], r["key"]) for r in uncited]


def test_one_citation_can_support_several_facts(conn):
    """The many-to-many model, exercised against real content."""
    row = conn.execute(
        "SELECT citation_id, COUNT(*) AS n FROM fact_citation "
        "GROUP BY citation_id ORDER BY n DESC LIMIT 1"
    ).fetchone()
    assert row["n"] > 1


def test_reloading_an_unchanged_pack_creates_no_revisions(conn, pack_dir):
    before = conn.execute("SELECT COUNT(*) AS n FROM article_revision").fetchone()["n"]
    report = PackLoader(conn).load_pack(pack_dir)
    after = conn.execute("SELECT COUNT(*) AS n FROM article_revision").fetchone()["n"]
    assert report.articles_revised == 0
    assert report.articles_created == 0
    assert after == before


def test_changed_content_creates_a_new_revision_and_keeps_the_old(conn, pack_dir, tmp_path):
    """Revisions are append-only: an edit must never overwrite history."""
    source = pack_dir / "articles" / "earth.json"
    data = json.loads(source.read_text(encoding="utf-8"))

    before = conn.execute(
        "SELECT r.id, r.version_major, r.version_minor FROM article_revision r "
        "JOIN article a ON a.id = r.article_id WHERE a.slug='earth' "
        "ORDER BY r.version_major, r.version_minor"
    ).fetchall()

    # Build a one-article pack with modified text.
    staging = tmp_path / "pack"
    (staging / "articles").mkdir(parents=True)
    for name in ("pack.json", "taxonomy.json", "sources.json"):
        (staging / name).write_text((pack_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
    data["content"]["adult"]["body"] += "\n\nAn additional paragraph. [1]"
    (staging / "articles" / "earth.json").write_text(json.dumps(data), encoding="utf-8")

    report = PackLoader(conn).load_pack(staging)
    assert report.articles_revised == 1

    after = conn.execute(
        "SELECT r.id, r.version_major, r.version_minor FROM article_revision r "
        "JOIN article a ON a.id = r.article_id WHERE a.slug='earth' "
        "ORDER BY r.version_major, r.version_minor"
    ).fetchall()
    assert len(after) == len(before) + 1
    # Every previous revision id still exists.
    assert {r["id"] for r in before} <= {r["id"] for r in after}
    assert after[-1]["version_minor"] == before[-1]["version_minor"] + 1


def test_loader_refuses_a_pack_with_validation_errors(empty_conn, pack_dir, tmp_path):
    staging = tmp_path / "bad"
    (staging / "articles").mkdir(parents=True)
    for name in ("pack.json", "taxonomy.json", "sources.json"):
        (staging / name).write_text((pack_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
    (staging / "articles" / "bad.json").write_text(json.dumps({
        "slug": "bad", "title": "Bad", "type": "science_concept",
        "categories": ["science"], "primary_category": "science",
        "content": {"adult": {"summary": "s", "body": "Nothing is cited here."}},
    }), encoding="utf-8")

    with pytest.raises(LoaderError, match="validation error"):
        PackLoader(empty_conn).load_pack(staging)

    assert empty_conn.execute(
        "SELECT COUNT(*) AS n FROM article WHERE slug='bad'"
    ).fetchone()["n"] == 0


def test_a_failed_load_rolls_back_completely(empty_conn, pack_dir, tmp_path):
    """A partially applied pack would leave the database internally inconsistent."""
    staging = tmp_path / "halfbad"
    (staging / "articles").mkdir(parents=True)
    for name in ("pack.json", "taxonomy.json"):
        (staging / name).write_text((pack_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
    # sources.json omitted entirely, so citations reference sources that do not exist.
    (staging / "sources.json").write_text("[]", encoding="utf-8")
    good = json.loads((pack_dir / "articles" / "earth.json").read_text(encoding="utf-8"))
    (staging / "articles" / "earth.json").write_text(json.dumps(good), encoding="utf-8")

    with pytest.raises(LoaderError):
        PackLoader(empty_conn).load_pack(staging)
    assert empty_conn.execute("SELECT COUNT(*) AS n FROM article").fetchone()["n"] == 0


def test_revisions_record_their_origin(conn):
    origins = {
        r["origin"]
        for r in conn.execute("SELECT DISTINCT origin FROM article_revision").fetchall()
    }
    assert origins <= {"human", "import", "ai_proposal", "ai_approved", "rollback"}
    assert "import" in origins


def test_audit_log_records_every_revision(conn):
    revisions = conn.execute("SELECT COUNT(*) AS n FROM article_revision").fetchone()["n"]
    audited = conn.execute(
        "SELECT COUNT(*) AS n FROM audit_log WHERE action='revision.created'"
    ).fetchone()["n"]
    assert audited >= revisions


def test_review_dates_follow_the_per_type_policy(conn):
    """Fast-moving subjects must be scheduled for review more often."""
    rows = conn.execute(
        "SELECT a.slug, t.key AS type_key, a.last_reviewed_at, a.next_review_at "
        "FROM article a JOIN article_type t ON t.id = a.type_id "
        "WHERE a.next_review_at IS NOT NULL"
    ).fetchall()
    assert rows
    for row in rows:
        assert row["next_review_at"] > row["last_reviewed_at"]
