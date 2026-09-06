"""The licensed importer and the bulk pack format.

Nothing here touches the network: the client is replaced with fixtures, so the
suite stays offline and deterministic while still exercising the mapping from
API records to validated articles.
"""

from __future__ import annotations

import gzip
import json
import re

import pytest

from encarta.config import Config
from encarta.content.loader import read_pack_articles
from encarta.content.validate import ContentValidator, has_errors
from encarta.pipeline.wikipedia import (
    MIN_EXTRACT_CHARS,
    SIMPLE_LEVEL,
    Subject,
    WikipediaImporter,
    slugify,
    strip_reference_markers,
)

LONG_EN = (
    "The tiger is the largest living member of the cat family, Felidae. "
    "It is a powerful predator native to Asia, hunting large ungulates such as "
    "deer and wild boar across a range that once extended from Turkey to the "
    "Russian Far East. Populations have declined sharply through habitat loss "
    "and poaching, and the species is now assessed as Endangered.\n\n"
    "Tigers are solitary and territorial, with large home ranges that vary with "
    "prey density. Their striped coat provides camouflage in the dappled light "
    "of forest and tall grassland."
)
LONG_SIMPLE = (
    "The tiger is a big cat. It lives in Asia and hunts other animals for food. "
    "Tigers have orange fur with black stripes, which helps them hide in long "
    "grass. Every tiger has its own pattern of stripes.\n\n"
    "There are not many tigers left in the wild. People have cut down the "
    "forests where they live, and some people hunt them illegally."
)


def en_record(title="Tiger", pageid=1001, revid=555, extract=LONG_EN):
    return {
        "title": title,
        "requested_as": title,
        "pageid": pageid,
        "revid": revid,
        "url": f"https://en.wikipedia.org/wiki/{title}",
        "description": "Largest species of the cat family",
        "extract": extract,
    }


def simple_record(title="Tiger", pageid=2002, revid=777, extract=LONG_SIMPLE):
    return {
        "title": title, "requested_as": title, "pageid": pageid, "revid": revid,
        "url": f"https://simple.wikipedia.org/wiki/{title}",
        "description": "", "extract": extract,
    }


@pytest.fixture
def importer(config, monkeypatch):
    """An importer with network permission granted but the client never used."""
    online = Config(
        data_dir=config.data_dir, content_dir=config.content_dir, allow_network=True
    )
    monkeypatch.setattr(
        "encarta.pipeline.wikipedia.WikipediaClient.__init__", lambda self, cfg: None
    )
    instance = WikipediaImporter(online)
    instance.client = None  # type: ignore[assignment]
    return instance


SUBJECT = Subject("Mammals", "animals", "animal")


# -- slugs -------------------------------------------------------------------

@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Tiger", "tiger"),
        ("Tyrannosaurus rex", "tyrannosaurus-rex"),
        ("Mercury (planet)", "mercury-planet"),
        ("Erwin Schrödinger", "erwin-schrodinger"),
        ("Ada Lovelace", "ada-lovelace"),
        ("Salt & pepper", "salt-and-pepper"),
        ("  spaced  out  ", "spaced-out"),
    ],
)
def test_slugify(title, expected):
    assert slugify(title) == expected


def test_slugs_match_the_validator_rule():
    from encarta.content.validate import SLUG_RE

    for title in ["Tiger", "Mercury (planet)", "Erwin Schrödinger", "C++"]:
        slug = slugify(title)
        if slug:
            assert SLUG_RE.match(slug), f"{title!r} -> {slug!r}"


# -- article construction ----------------------------------------------------

def test_builds_a_valid_article(importer):
    article = importer._article(SUBJECT, en_record(), simple_record())
    assert article is not None
    assert article["slug"] == "tiger"
    assert article["type"] == "animal"
    assert article["primary_category"] == "animals"
    assert set(article["content"]) == {"adult", SIMPLE_LEVEL}


def test_imported_article_passes_validation(importer):
    article = importer._article(SUBJECT, en_record(), simple_record())
    validator = ContentValidator(
        known_sources={c["source"] for c in article["citations"]},
        known_types={"animal"},
        known_categories={"animals"},
    )
    findings = validator.validate_article(article, where="fixture")
    assert not has_errors(findings), [str(f) for f in findings]


def test_two_levels_come_from_two_different_sources(importer):
    """The whole justification for the 9-12 level is that it is a different
    text, not a truncation of the adult one."""
    article = importer._article(SUBJECT, en_record(), simple_record())
    adult = article["content"]["adult"]["body"]
    simple = article["content"][SIMPLE_LEVEL]["body"]
    assert adult != simple
    assert article["citations"][0]["source"] != article["citations"][1]["source"]


def test_missing_simple_article_yields_adult_only(importer):
    article = importer._article(SUBJECT, en_record(), None)
    assert set(article["content"]) == {"adult"}
    assert len(article["citations"]) == 1


def test_identical_simple_text_is_not_offered_as_a_second_level(importer):
    """If Simple English is a byte-for-byte copy, presenting it as a children's
    level would be a lie the validator would also reject."""
    article = importer._article(SUBJECT, en_record(), simple_record(extract=LONG_EN))
    assert set(article["content"]) == {"adult"}


def test_too_short_extracts_are_skipped(importer):
    assert importer._article(SUBJECT, en_record(extract="Stub."), None) is None
    assert importer.report.skipped_short == 1


def test_body_carries_a_citation_marker(importer):
    article = importer._article(SUBJECT, en_record(), simple_record())
    assert "[1]" in article["content"]["adult"]["body"]
    assert "[2]" in article["content"][SIMPLE_LEVEL]["body"]


def test_wikipedia_reference_superscripts_are_stripped():
    """`[n]` means "citation n" here, so an inherited one is a false link."""
    assert strip_reference_markers("Tigers are big[2] cats[17].") == "Tigers are big cats."
    assert strip_reference_markers("Disputed[citation needed] claim.") == "Disputed claim."
    assert strip_reference_markers("See the note[note 3] there.") == "See the note there."


def test_stripping_references_leaves_ordinary_bracketed_text_alone():
    """The cleaner must not eat real content that happens to use brackets.

    Letter markers stay: our citations are numbered, so "[a]" is not a false
    link, and removing it would cost real text for no safety gain.
    """
    for text in (
        "The formula [Fe(CN)6] is complex.",
        "He said [sic] and moved on.",
        "Ranges like [0, 1] are intervals.",
        "The array index [i] varies.",
        "Ambiguous[a] wording[b].",
    ):
        assert strip_reference_markers(text) == text


def test_imported_body_has_no_marker_without_a_citation(importer):
    """The whole article, end to end: no marker may lack a citation.

    Six real articles in the harvest failed exactly this — one carried [2]
    through [17] from Wikipedia's own reference list.
    """
    messy = (
        "The tiger is the largest living cat[2] in the family Felidae.[3] "
        "It is native to Asia and hunts large ungulates such as deer.[4][5] "
        "Populations have declined through habitat loss[citation needed] and "
        "poaching, and the species is assessed as Endangered by the IUCN.\n\n"
        "Tigers are solitary and territorial animals with large home ranges "
        "that vary considerably with the local density of available prey."
    )
    article = importer._article(SUBJECT, en_record(extract=messy), None)
    used = {int(m) for m in re.findall(r"\[(\d{1,3})\]", article["content"]["adult"]["body"])}
    defined = {c["marker"] for c in article["citations"]}
    assert used == {1}, f"stray markers survived: {sorted(used - {1})}"
    assert not used - defined


def test_extract_length_floor_is_enforced(importer):
    filler = "This sentence is long enough to survive paragraph filtering. " * 2
    assert len(filler) < MIN_EXTRACT_CHARS
    assert importer._article(SUBJECT, en_record(extract=filler), None) is None


# -- attribution -------------------------------------------------------------

def test_sources_carry_licence_and_a_permanent_revision_link(importer):
    sources = importer._sources([(en_record(), simple_record())])
    assert len(sources) == 2
    for source in sources:
        assert source["license"] == "CC BY-SA 4.0"
        assert source["license_url"].startswith("https://creativecommons.org/")
        # A permanent link is what makes CC BY-SA attribution checkable: the
        # revision's history names the authors.
        assert "oldid=" in source["url"]
        assert source["publisher"] == "Wikipedia contributors"
        assert source["tier"] == 3, "an encyclopaedia is a tertiary source, not tier 1"


def test_source_uids_match_the_citations(importer):
    en, simple = en_record(), simple_record()
    article = importer._article(SUBJECT, en, simple)
    sources = importer._sources([(en, simple)])
    assert {c["source"] for c in article["citations"]} == {s["uid"] for s in sources}


# -- bulk pack format --------------------------------------------------------

def test_reads_a_gzipped_jsonl_pack(tmp_path):
    pack = tmp_path / "bulk"
    pack.mkdir()
    rows = [{"slug": f"a-{n}", "title": f"A {n}"} for n in range(3)]
    with gzip.open(pack / "articles.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    read = read_pack_articles(pack)
    assert [a["slug"] for _, a in read] == ["a-0", "a-1", "a-2"]
    assert all(label.startswith("articles.jsonl.gz:") for label, _ in read)


def test_loose_and_bulk_articles_can_coexist(tmp_path):
    pack = tmp_path / "mixed"
    (pack / "articles").mkdir(parents=True)
    (pack / "articles" / "hand.json").write_text(
        json.dumps({"slug": "hand", "title": "Hand written"}), encoding="utf-8")
    with gzip.open(pack / "articles.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"slug": "bulk", "title": "Bulk"}) + "\n")

    slugs = {a["slug"] for _, a in read_pack_articles(pack)}
    assert slugs == {"hand", "bulk"}


def test_malformed_bulk_line_is_reported_with_its_line_number(tmp_path):
    from encarta.content.loader import LoaderError

    pack = tmp_path / "broken"
    pack.mkdir()
    (pack / "articles.jsonl").write_text('{"slug": "ok"}\nnot json\n', encoding="utf-8")
    with pytest.raises(LoaderError, match="line 2"):
        read_pack_articles(pack)


def test_empty_pack_reads_as_empty(tmp_path):
    pack = tmp_path / "empty"
    pack.mkdir()
    assert read_pack_articles(pack) == []


# -- network gate ------------------------------------------------------------

def test_client_refuses_without_network_permission(config):
    from encarta.pipeline.wikipedia import WikipediaClient

    offline = Config(data_dir=config.data_dir, content_dir=config.content_dir,
                     allow_network=False)
    with pytest.raises(PermissionError, match="ENCARTA_ALLOW_NETWORK"):
        WikipediaClient(offline)


def test_hand_written_slugs_are_never_overwritten(importer):
    """Authored articles outrank imported extracts on the same subject."""
    importer.exclude.add("tiger")
    assert importer._article(SUBJECT, en_record(), simple_record()) is None


def test_imported_articles_are_not_marked_kids_safe(importer):
    """Kids Mode is a vetted subset, and nobody has read these.

    The harvest spans wars, battles, diseases and human anatomy. Importing
    cleanly is not the same as being reviewed for a child, and the safe default
    is the one that cannot be undone after the fact.
    """
    article = importer._article(SUBJECT, en_record(), simple_record())
    assert article["kids_safe"] is False
    # And the pairing the validator enforces: no children's reading band on an
    # article nobody has reviewed for children.
    assert not {"age6_8", "age9_12"} & set(article["content"])


def test_imported_articles_stay_out_of_kids_mode_after_loading(
    tmp_path, importer, writable_conn
):
    """The flag has to survive the loader, not just the importer.

    Loaded into a database that already carries the real taxonomy, so this
    exercises the shipping loader path rather than a synthetic one.
    """
    from encarta.content.loader import PackLoader

    article = importer._article(SUBJECT, en_record(), simple_record())
    sources = importer._sources([(en_record(), simple_record())])

    pack = tmp_path / "imported"
    pack.mkdir()
    (pack / "pack.json").write_text(json.dumps({
        "key": "imported", "title": "Imported", "version": "1.0.0",
        "description": "Test import",
    }), encoding="utf-8")
    (pack / "articles.jsonl").write_text(
        json.dumps(article) + chr(10), encoding="utf-8")
    (pack / "sources.json").write_text(json.dumps(sources), encoding="utf-8")

    PackLoader(writable_conn, strict=False).load_pack(pack)
    row = writable_conn.execute(
        "SELECT kids_safe FROM article WHERE slug = ?", (article["slug"],)
    ).fetchone()
    assert row is not None, "the article should have loaded"
    assert row["kids_safe"] == 0, "an unreviewed import must not reach Kids Mode"
