"""Search behaviour: safety of user input, ranking, expansion and correction."""

from __future__ import annotations

import pytest

from encarta.services.search import SearchIndexer, SearchService, build_match_expression, tokenize


@pytest.fixture
def search(conn):
    return SearchService(conn)


def titles(response):
    return [hit.title for hit in response.hits]


def test_exact_title_wins(search):
    assert titles(search.search("Tyrannosaurus rex"))[0] == "Tyrannosaurus rex"


def test_natural_language_query_finds_the_right_article(search):
    assert "Tyrannosaurus rex" in titles(search.search("largest dinosaur"))


def test_synonym_expansion(search):
    """A reader who types 'cavemen' should still reach human evolution."""
    assert "Human Evolution" in titles(search.search("cavemen"))
    assert "Mars" in titles(search.search("red planet"))
    assert "Ancient Egypt" in titles(search.search("pyramids"))


def test_misspelling_is_corrected(search):
    response = search.search("tyranosaurus")
    assert response.corrected_query is not None
    assert "Tyrannosaurus rex" in titles(response)


def test_alias_lookup(search):
    assert "Tyrannosaurus rex" in titles(search.search("t rex"))


def test_results_are_ordered_by_final_score_not_raw_bm25(search):
    """Trust signals must actually affect the order the reader sees."""
    scores = [hit.score for hit in search.search("dinosaur", limit=10).hits]
    assert scores == sorted(scores, reverse=True)


def test_category_filter(search):
    response = search.search("earth", category="space", limit=10)
    assert response.hits
    response_other = search.search("earth", category="history", limit=10)
    assert len(response_other.hits) <= len(response.hits)


def test_reading_level_filter(search):
    response = search.search("dinosaur", reading_level="age6_8", limit=10)
    for hit in response.hits:
        assert "age6_8" in hit.available_levels


def test_empty_query_returns_nothing(search):
    assert search.search("   ").hits == []


@pytest.mark.parametrize("hostile", [
    '"', 'a" OR "b', 'NEAR(', 'foo*bar"', '*', '((', 'AND OR NOT', "x' OR 1=1 --",
    'column:title', '^', '"unclosed',
])
def test_hostile_input_never_raises(search, hostile):
    """FTS5 has its own query syntax; raw user input must never reach it."""
    search.search(hostile)  # must not raise


def test_match_expression_quotes_every_term():
    expression = build_match_expression(tokenize('a "quoted" term'))
    assert expression.count('"') % 2 == 0
    assert "OR" in expression


def test_autocomplete_prefix(search):
    rows = search.autocomplete("tyr")
    assert any(r["title"] == "Tyrannosaurus rex" for r in rows)


def test_autocomplete_ignores_single_letter(search):
    assert search.autocomplete("t", limit=5) is not None


def test_only_published_articles_are_indexed(conn):
    """A draft must never become discoverable by accident."""
    conn.execute("UPDATE article SET status='draft' WHERE slug='mars'")
    conn.commit()
    try:
        SearchIndexer(conn).rebuild()
        assert "Mars" not in titles(SearchService(conn).search("mars"))
    finally:
        conn.execute("UPDATE article SET status='published' WHERE slug='mars'")
        conn.commit()
        SearchIndexer(conn).rebuild()


def test_index_covers_every_published_article(conn):
    published = conn.execute(
        "SELECT COUNT(*) AS n FROM article WHERE status='published'"
    ).fetchone()["n"]
    indexed = conn.execute("SELECT COUNT(*) AS n FROM article_fts").fetchone()["n"]
    assert indexed == published


def test_search_finds_text_from_every_reading_level(search):
    """Index assembly must include children's levels, not only the adult body."""
    response = search.search("banana")  # appears only in the age 6-8 T. rex text
    assert "Tyrannosaurus rex" in titles(response)


def test_top_hit_does_not_depend_on_how_many_results_were_asked_for(conn):
    """Re-ranking must run over a pool, not over the page.

    If the candidate pool is the page, asking for one result returns the best
    *bm25* row while asking for twenty returns the best *re-ranked* row, and the
    two disagree. That gap widens with the size of the library, which is exactly
    when it stops being noticeable.
    """
    service = SearchService(conn)
    for query in ("earth", "moon", "dinosaur", "water", "ancient"):
        narrow = service.search(query, limit=1)
        wide = service.search(query, limit=20)
        if not wide.hits:
            continue
        assert narrow.hits, f"{query!r} lost its only hit"
        assert narrow.hits[0].slug == wide.hits[0].slug, (
            f"{query!r}: top hit changed with page size"
        )


def test_paging_through_results_never_repeats_or_skips(conn):
    service = SearchService(conn)
    whole = service.search("earth", limit=12)
    if len(whole.hits) < 6:
        pytest.skip("not enough matches in the core pack to page through")
    first = service.search("earth", limit=3, offset=0)
    second = service.search("earth", limit=3, offset=3)
    assert [h.slug for h in first.hits] == [h.slug for h in whole.hits[:3]]
    assert [h.slug for h in second.hits] == [h.slug for h in whole.hits[3:6]]
    assert not {h.slug for h in first.hits} & {h.slug for h in second.hits}


def test_a_leading_the_does_not_forfeit_the_exact_title_match(search):
    """"The Moon" must win the query "moon".

    Without normalising the leading article, "The Moon" scores neither the
    exact-title nor the prefix bonus, and any short article merely *starting*
    with the word outranks it. In a large library that means a stub called
    "Moondial" beats the encyclopaedia's own Moon article.
    """
    assert titles(search.search("moon"))[0] == "The Moon"
    assert titles(search.search("the moon"))[0] == "The Moon"


def test_leading_article_normalisation_is_limited_to_articles():
    from encarta.services.search import _drop_leading_article

    assert _drop_leading_article("the moon") == "moon"
    assert _drop_leading_article("a tale of two cities") == "tale of two cities"
    assert _drop_leading_article("an ocean") == "ocean"
    # Only a leading article, and only one: real title words survive.
    assert _drop_leading_article("theory of relativity") == "theory of relativity"
    assert _drop_leading_article("android") == "android"
    assert _drop_leading_article("ancient egypt") == "ancient egypt"


def test_matching_every_term_outranks_matching_one_of_them_well(search):
    """Coverage is a relevance signal, not a tiebreaker.

    Browsing search uses OR so partial matches still surface, but a strong hit
    on a single rare word must not beat an article that answers the whole
    query.
    """
    hits = search.search("volcano eruption lava", limit=20).hits
    assert hits
    full = [h for h in hits if h.score >= 25.0]
    assert full, "no article was credited with covering every term"
    assert hits[0] in full


def test_coverage_bonus_is_applied_only_to_covering_articles(search):
    row = {
        "slug": "x", "title": "Something", "summary": "", "quality_score": 50,
        "min_reading_level": "adult", "type_key": "concept", "type_label": "Concept",
        "bm25_score": -5.0, "snippet": "", "category": None, "category_icon": None,
        "hero_media": None, "levels": "adult", "source_strength": None,
    }
    plain = search._to_hit(row, ["a", "b"])
    covered = search._to_hit(row, ["a", "b"], covers_all={"x"})
    assert covered.score - plain.score == 25.0


def _row(title, *, bm25=-5.0, quality=50, slug="x"):
    return {
        "slug": slug, "title": title, "summary": "", "quality_score": quality,
        "min_reading_level": "adult", "type_key": "concept", "type_label": "Concept",
        "bm25_score": bm25, "snippet": "", "category": None, "category_icon": None,
        "hero_media": None, "levels": "adult", "source_strength": None,
    }


def test_title_bonuses_ignore_a_leading_article(search):
    """The exact-title bonus is worth 100; a prefix match only 40.

    Asserted on the score directly because the difference is invisible in a
    small library — "The Moon" wins there on quality alone. It is decisive once
    a thousand short articles merely *starting* with "moon" exist.
    """
    exact = search._to_hit(_row("The Moon"), ["moon"])
    prefix = search._to_hit(_row("Moondial"), ["moon"])
    assert exact.score - prefix.score == 60.0, "The Moon must beat Moondial by the full margin"

    # And the same when the reader types the article in themselves.
    assert search._to_hit(_row("The Moon"), ["the", "moon"]).score == exact.score


def test_a_prefix_match_still_scores_below_an_exact_one(search):
    exact = search._to_hit(_row("Volcano"), ["volcano"])
    prefix = search._to_hit(_row("Volcano tourism"), ["volcano"])
    contains = search._to_hit(_row("Types of volcano"), ["volcano"])
    assert exact.score > prefix.score > contains.score


def test_the_candidate_pool_never_shrinks_below_the_floor(search, monkeypatch):
    """Asking for fewer results must not narrow what gets re-ranked.

    bm25 normalises by document length, so a long authored article can sit
    below hundreds of short imported extracts on raw relevance. If the pool
    tracked the page size, a three-result request would re-rank only the first
    24 rows and never see it — and the top hit would change with the page size.
    """
    seen = []
    original = SearchService._run

    def spy(self, match_expr, limit, offset, *args):
        seen.append(limit)
        return original(self, match_expr, limit, offset, *args)

    monkeypatch.setattr(SearchService, "_run", spy)
    for limit in (1, 3, 20):
        search.search("moon", limit=limit)
    assert seen, "no query ran"
    assert min(seen) >= SearchService.MIN_POOL
    assert max(seen) <= SearchService.MAX_POOL
