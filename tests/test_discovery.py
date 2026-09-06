"""Home-page discovery, and what a large imported pack does to it.

Importing tens of thousands of reference extracts changes the *statistics* of
the library without changing any single article. These tests exist because the
home page is chosen by ranking, and a bulk import quietly rigs every ranking
that is not explicitly defended: the imports are the newest rows, and they
outnumber the authored articles by two orders of magnitude.
"""

from __future__ import annotations

from encarta.repositories import DiscoveryRepository


def test_featured_prefers_well_evidenced_articles(conn):
    rows = DiscoveryRepository(conn).featured(6)
    assert rows, "the core pack should always fill the featured strip"
    scores = [r["quality_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_did_you_know_never_offers_an_unlabelled_claim(conn):
    """Every surfaced fact carries its epistemic status, or it must not appear."""
    for row in DiscoveryRepository(conn).did_you_know(5):
        assert row["epistemic"] in ("fact", "estimate")
        assert row["slug"], "a fact with no article behind it is unciteable"


def _simulate_bulk_import(conn, keep: int = 4) -> set[str]:
    """Demote all but `keep` articles to import-like rows: low score, newest.

    This is what loading a large Wikipedia pack does to the article table.
    """
    good = [
        r["slug"] for r in conn.execute(
            "SELECT slug FROM article WHERE status='published' "
            "ORDER BY quality_score DESC LIMIT ?", (keep,)
        ).fetchall()
    ]
    placeholders = ",".join("?" * len(good))
    conn.execute(
        f"UPDATE article SET quality_score = 22, "
        f"updated_at = '2099-01-01T00:00:00Z' WHERE slug NOT IN ({placeholders})",
        good,
    )
    conn.commit()
    return set(good)


def test_daily_discovery_does_not_surface_a_thin_import(writable_conn):
    good = _simulate_bulk_import(writable_conn)
    pick = DiscoveryRepository(writable_conn).daily_discovery()
    assert pick is not None
    # The seed is the calendar date, so state the invariant as well as the
    # membership: the pick must clear the floor on every possible day.
    assert pick["quality_score"] >= DiscoveryRepository.SHOWCASE_FLOOR
    assert pick["slug"] in good


def test_recently_updated_survives_a_bulk_import(writable_conn):
    """A pack load stamps thousands of rows with one timestamp.

    Ordering by `updated_at` alone would hand the whole section to the import.
    """
    good = _simulate_bulk_import(writable_conn)
    rows = DiscoveryRepository(writable_conn).recently_updated(limit=len(good))
    assert {r["slug"] for r in rows} == good


def test_the_showcase_floor_falls_back_rather_than_emptying_the_page(writable_conn):
    """A small or brand-new library must still have a home page."""
    writable_conn.execute("UPDATE article SET quality_score = 5")
    writable_conn.commit()
    repo = DiscoveryRepository(writable_conn)
    assert repo.daily_discovery() is not None
    assert len(repo.recently_updated(6)) == 6


def test_a_short_showcase_keeps_its_good_rows_and_tops_up(writable_conn):
    """Falling back must not throw away the quality rows it already found."""
    good = _simulate_bulk_import(writable_conn, keep=2)
    rows = DiscoveryRepository(writable_conn).recently_updated(6)
    assert len(rows) == 6, "the home page must still fill"
    slugs = [r["slug"] for r in rows]
    assert good <= set(slugs), "the two good articles were dropped by the fallback"
    assert len(slugs) == len(set(slugs)), "top-up duplicated a row"
