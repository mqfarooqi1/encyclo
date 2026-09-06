"""Domain model.

These types are the vocabulary the whole application shares. Two of them carry
most of the product's weight:

``Epistemic``  -- how strongly a statement is known. The UI must render an
                 estimate or a contested claim differently from an established
                 fact, and the AI layer is forbidden from promoting anything up
                 this scale.

``ReadingLevel`` -- each level is independently authored content for a real
                 audience, not a truncation of the adult text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


class ReadingLevel(StrEnum):
    AGE_6_8 = "age6_8"
    AGE_9_12 = "age9_12"
    TEEN = "teen"
    ADULT = "adult"


# Ordered simplest to most advanced. Used for fallback: if a reader asks for a
# level an article does not have, we step UP to the next available level rather
# than showing nothing, and the UI says which level it actually gave them.
READING_LEVELS: tuple[ReadingLevel, ...] = (
    ReadingLevel.AGE_6_8,
    ReadingLevel.AGE_9_12,
    ReadingLevel.TEEN,
    ReadingLevel.ADULT,
)

_LEVEL_LABELS = {
    ReadingLevel.AGE_6_8: "Ages 6-8",
    ReadingLevel.AGE_9_12: "Ages 9-12",
    ReadingLevel.TEEN: "Teen",
    ReadingLevel.ADULT: "Adult",
}

_LEVEL_DESCRIPTIONS = {
    ReadingLevel.AGE_6_8: "Short sentences and familiar words.",
    ReadingLevel.AGE_9_12: "Clear explanations with real scientific vocabulary.",
    ReadingLevel.TEEN: "Fuller detail, mechanisms and evidence.",
    ReadingLevel.ADULT: "Full encyclopaedia treatment.",
}


def level_label(level: ReadingLevel | str) -> str:
    return _LEVEL_LABELS.get(ReadingLevel(level), str(level))


def level_description(level: ReadingLevel | str) -> str:
    return _LEVEL_DESCRIPTIONS.get(ReadingLevel(level), "")


def resolve_level(
    requested: ReadingLevel | str, available: set[str] | frozenset[str]
) -> ReadingLevel | None:
    """Pick the best available reading level for a request.

    Steps upward from the requested level (more advanced), then downward, so a
    reader always gets something real. Returns None if the article has no
    content at all.
    """
    if not available:
        return None
    want = ReadingLevel(requested)
    index = READING_LEVELS.index(want)
    for candidate in (*READING_LEVELS[index:], *reversed(READING_LEVELS[:index])):
        if candidate.value in available:
            return candidate
    return None


class Epistemic(StrEnum):
    """How strongly a statement is known. Never upgrade a value on this scale
    without new evidence and a recorded review."""

    FACT = "fact"
    ESTIMATE = "estimate"
    INTERPRETATION = "interpretation"
    OPINION = "opinion"
    UNCERTAIN = "uncertain"
    CONTESTED = "contested"


EPISTEMIC_LABELS = {
    Epistemic.FACT: "Established",
    Epistemic.ESTIMATE: "Estimate",
    Epistemic.INTERPRETATION: "Interpretation",
    Epistemic.OPINION: "Opinion",
    Epistemic.UNCERTAIN: "Uncertain",
    Epistemic.CONTESTED: "Debated",
}

# Anything not FACT must be visually marked in the UI.
NEEDS_QUALIFIER: frozenset[Epistemic] = frozenset(
    {
        Epistemic.ESTIMATE,
        Epistemic.INTERPRETATION,
        Epistemic.OPINION,
        Epistemic.UNCERTAIN,
        Epistemic.CONTESTED,
    }
)


class SourceTier(IntEnum):
    """Source ranking. See docs/SOURCE_POLICY.md.

    AI-generated text is never a source at any tier.
    """

    AUTHORITATIVE = 1  # government, university, peer-reviewed, national museum
    INSTITUTIONAL = 2  # major educational or professional body
    SECONDARY = 3  # reputable secondary reference
    GENERAL = 4  # general web


class Verification(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    BROKEN = "broken"
    MOVED = "moved"
    PAYWALLED = "paywalled"


class RelationKind(StrEnum):
    PART_OF = "part_of"
    MEMBER_OF = "member_of"
    LIVED_DURING = "lived_during"
    LOCATED_IN = "located_in"
    DISCOVERED_BY = "discovered_by"
    STUDIED_BY = "studied_by"
    PRECEDED_BY = "preceded_by"
    SUCCEEDED_BY = "succeeded_by"
    CAUSES = "causes"
    CONTRASTS_WITH = "contrasts_with"
    EXAMPLE_OF = "example_of"
    RELATED = "related"


RELATION_LABELS = {
    RelationKind.PART_OF: "part of",
    RelationKind.MEMBER_OF: "member of",
    RelationKind.LIVED_DURING: "lived during",
    RelationKind.LOCATED_IN: "located in",
    RelationKind.DISCOVERED_BY: "discovered by",
    RelationKind.STUDIED_BY: "studied by",
    RelationKind.PRECEDED_BY: "preceded by",
    RelationKind.SUCCEEDED_BY: "followed by",
    RelationKind.CAUSES: "leads to",
    RelationKind.CONTRASTS_WITH: "compared with",
    RelationKind.EXAMPLE_OF: "example of",
    RelationKind.RELATED: "related to",
}

# Reading the graph backwards needs the inverse wording, so "Cretaceous Period"
# shows "lived here: T. rex" rather than a nonsensical "lived during".
INVERSE_RELATION_LABELS = {
    RelationKind.PART_OF: "includes",
    RelationKind.MEMBER_OF: "includes",
    RelationKind.LIVED_DURING: "home to",
    RelationKind.LOCATED_IN: "contains",
    RelationKind.DISCOVERED_BY: "discovered",
    RelationKind.STUDIED_BY: "studied",
    RelationKind.PRECEDED_BY: "followed by",
    RelationKind.SUCCEEDED_BY: "preceded by",
    RelationKind.CAUSES: "caused by",
    RelationKind.CONTRASTS_WITH: "compared with",
    RelationKind.EXAMPLE_OF: "examples include",
    RelationKind.RELATED: "related to",
}


@dataclass(slots=True)
class Source:
    uid: str
    title: str
    publisher: str
    tier: SourceTier = SourceTier.GENERAL
    source_type: str = "web"
    url: str | None = None
    authors: str | None = None
    published_date: str | None = None
    accessed_date: str | None = None
    doi: str | None = None
    isbn: str | None = None
    license: str | None = None
    verification_status: Verification = Verification.UNVERIFIED
    notes: str | None = None

    @property
    def short_ref(self) -> str:
        bits = [self.publisher]
        if self.published_date:
            bits.append(self.published_date[:4])
        return ", ".join(b for b in bits if b)


@dataclass(slots=True)
class Citation:
    marker: int
    source_uid: str
    claim: str
    supports: str = "supports"
    locator: str | None = None
    quote: str | None = None
    fact_key: str | None = None


@dataclass(slots=True)
class Fact:
    key: str
    label: str
    value_text: str
    value_num: float | None = None
    unit: str | None = None
    epistemic: Epistemic = Epistemic.FACT
    confidence: float | None = None
    group_label: str | None = None
    comparable_key: str | None = None
    sort_order: int = 0

    @property
    def needs_qualifier(self) -> bool:
        return self.epistemic in NEEDS_QUALIFIER


@dataclass(slots=True)
class ArticleContent:
    reading_level: ReadingLevel
    summary: str
    body_md: str
    word_count: int = 0
    reading_time_min: int = 1
    readability_grade: float | None = None


@dataclass(slots=True)
class MediaRef:
    media_uid: str
    role: str = "inline"
    caption: str | None = None
    alt_text: str = ""
    sort_order: int = 0


@dataclass(slots=True)
class Article:
    slug: str
    title: str
    type_key: str
    summary: str = ""
    status: str = "published"
    aliases: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    primary_category: str | None = None
    pronunciation_ipa: str | None = None
    kids_safe: bool = True
    content: list[ArticleContent] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    media: list[MediaRef] = field(default_factory=list)
    quality_score: int | None = None
    last_reviewed_at: str | None = None
    next_review_at: str | None = None

    @property
    def available_levels(self) -> set[str]:
        return {c.reading_level.value for c in self.content}
