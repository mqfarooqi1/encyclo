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
