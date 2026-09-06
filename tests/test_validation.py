"""The content validator is the gate every article passes through.

These tests pin the editorial rules: if one of them stops holding, unsourced or
age-inappropriate content could reach readers.
"""

from __future__ import annotations

import json

import pytest

from encarta.content.validate import ContentValidator, has_errors

BASE = {
    "slug": "test-article",
    "title": "Test Article",
    "type": "science_concept",
    "categories": ["science"],
    "primary_category": "science",
    "summary": "A summary.",
    "content": {
        "adult": {"summary": "s", "body": "The claim is supported. [1]"},
    },
    "citations": [
        {"marker": 1, "source": "src-a", "claim": "Supports the claim.", "supports": "supports"}
    ],
    "facts": [{"key": "k", "label": "K", "value": "v", "cite": [1]}],
}


@pytest.fixture
def validator():
    return ContentValidator(
        known_sources={"src-a", "src-b"},
        known_media={"img-a"},
        known_slugs={"test-article", "other"},
        known_types={"science_concept"},
        known_categories={"science", "space"},
    )


def article(**overrides):
    data = json.loads(json.dumps(BASE))
    data.update(overrides)
    return data


def kinds(findings, severity=None):
    return {f.kind for f in findings if severity is None or f.severity == severity}


def test_valid_article_passes(validator):
    assert not has_errors(validator.validate_article(article()))


def test_adult_level_is_mandatory(validator):
    findings = validator.validate_article(
        article(content={"age6_8": {"summary": "s", "body": "Simple. [1]"}})
    )
    assert "missing_reading_level" in kinds(findings, "error")


def test_published_article_must_cite_something(validator):
    findings = validator.validate_article(
        article(content={"adult": {"summary": "s", "body": "Uncited claim."}}, citations=[],
                facts=[])
    )
    assert "missing_citation" in kinds(findings, "error")


def test_body_citing_an_undefined_marker_is_an_error(validator):
    findings = validator.validate_article(
        article(content={"adult": {"summary": "s", "body": "Claim. [1] Another. [7]"}})
    )
    assert "dangling_citation" in kinds(findings, "error")


def test_fact_citing_an_undefined_marker_is_an_error(validator):
    findings = validator.validate_article(
        article(facts=[{"key": "k", "label": "K", "value": "v", "cite": [9]}])
    )
    assert "dangling_citation" in kinds(findings, "error")


def test_uncited_established_fact_is_flagged(validator):
    """A fact presented as settled must be traceable, or downgraded to an estimate."""
    findings = validator.validate_article(
        article(facts=[{"key": "k", "label": "K", "value": "v"}])
    )
    assert "missing_citation" in kinds(findings, "warning")


def test_estimate_without_a_citation_is_not_flagged_as_missing(validator):
    findings = validator.validate_article(
        article(facts=[{"key": "k", "label": "K", "value": "v",
                        "epistemic": "estimate", "confidence": 0.5}])
    )
    assert "missing_citation" not in kinds(findings, "warning")


def test_childrens_level_copied_from_adult_is_rejected(validator):
    """Each reading level must be authored for its audience, not truncated."""
    body = "The same words at both levels. [1]"
    findings = validator.validate_article(
        article(content={"adult": {"summary": "s", "body": body},
                         "age6_8": {"summary": "s", "body": body}})
    )
    assert "duplicated_reading_level" in kinds(findings, "error")


def test_adult_prose_in_a_childrens_level_is_flagged(validator):
    long_sentence = " ".join(["word"] * 40) + " with a citation [1]."
    findings = validator.validate_article(
        article(content={"adult": {"summary": "s", "body": "Short. [1]"},
                         "age6_8": {"summary": "s", "body": long_sentence}})
    )
    assert "reading_level_too_hard" in kinds(findings, "warning")


def test_media_without_alt_text_is_an_error(validator):
    findings = validator.validate_article(
        article(media=[{"uid": "img-a", "role": "hero", "alt": ""}])
    )
    assert "missing_alt_text" in kinds(findings, "error")


def test_unknown_source_is_rejected(validator):
    findings = validator.validate_article(
        article(citations=[{"marker": 1, "source": "nope", "claim": "c"}])
    )
    assert "unknown_source" in kinds(findings, "error")


def test_citation_without_a_claim_is_rejected(validator):
    """A bare source reference does not say what it is evidence for."""
    findings = validator.validate_article(
        article(citations=[{"marker": 1, "source": "src-a", "claim": "  "}])
    )
    assert "uncited_claim" in kinds(findings, "error")


def test_relation_to_a_missing_article_is_a_warning(validator):
    findings = validator.validate_article(
        article(relations=[{"to": "does-not-exist", "kind": "related"}])
    )
    assert "orphan_relation" in kinds(findings, "warning")


def test_self_relation_is_rejected(validator):
    findings = validator.validate_article(
        article(relations=[{"to": "test-article", "kind": "related"}])
    )
    assert "bad_relation" in kinds(findings, "error")


def test_kids_unsafe_article_cannot_offer_childrens_levels(validator):
    findings = validator.validate_article(
        article(kids_safe=False,
                content={"adult": {"summary": "s", "body": "Adult. [1]"},
                         "age9_12": {"summary": "s", "body": "For children. [1]"}})
    )
    assert "kids_safety" in kinds(findings, "error")


def test_bad_slug_is_rejected(validator):
    assert "bad_slug" in kinds(validator.validate_article(article(slug="Not A Slug")), "error")


def test_two_hero_images_is_rejected(validator):
    findings = validator.validate_article(article(media=[
        {"uid": "img-a", "role": "hero", "alt": "a"},
        {"uid": "img-a", "role": "hero", "alt": "b"},
    ]))
    assert "bad_media" in kinds(findings, "error")


def test_shipped_core_pack_has_no_validation_errors(pack_dir):
    """The pack we actually ship must satisfy its own rules."""
    taxonomy = json.loads((pack_dir / "taxonomy.json").read_text(encoding="utf-8"))
    sources = json.loads((pack_dir / "sources.json").read_text(encoding="utf-8"))
    files = sorted((pack_dir / "articles").glob("*.json"))
    articles = [json.loads(f.read_text(encoding="utf-8")) for f in files]

    validator = ContentValidator(
        known_sources={s["uid"] for s in sources},
        known_slugs={a["slug"] for a in articles},
        known_types={t["key"] for t in taxonomy["types"]},
        known_categories={c["key"] for c in taxonomy["categories"]},
    )
    errors = []
    for path, art in zip(files, articles, strict=True):
        errors.extend(
            f for f in validator.validate_article(art, where=path.name) if f.severity == "error"
        )
    assert not errors, "\n".join(str(e) for e in errors)
