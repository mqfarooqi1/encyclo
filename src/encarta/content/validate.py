"""Content validation.

This module is the gate every article passes through before it can enter the
database. It encodes the project's editorial rules as executable checks, so
"every important claim is cited" is enforced rather than merely aspired to.

Severity contract:
  ERROR   -- refuses the load. The content is structurally or editorially unsafe.
  WARNING -- loads, but raises an ``issue`` row for the admin review queue.
  INFO    -- advisory only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..domain.models import READING_LEVELS, Epistemic, ReadingLevel

ERROR = "error"
WARNING = "warning"
INFO = "info"

# Matches the [1] / [12] citation markers embedded in body markdown.
CITATION_MARKER_RE = re.compile(r"\[(\d{1,3})\]")

VALID_SUPPORTS = {"supports", "partially", "background", "contradicts"}
VALID_MEDIA_ROLES = {"hero", "inline", "gallery", "diagram", "map", "pronunciation"}
VALID_RELATION_KINDS = {
    "part_of", "member_of", "lived_during", "located_in", "discovered_by",
    "studied_by", "preceded_by", "succeeded_by", "causes", "contrasts_with",
    "example_of", "related",
}

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Reading levels aimed at children. Content offered to these levels gets the
# stricter safety and vocabulary checks.
KIDS_LEVELS = {ReadingLevel.AGE_6_8.value, ReadingLevel.AGE_9_12.value}

# Rough sentence-length ceilings per level. Not a readability score -- a blunt
# guard that adult prose has not simply been pasted into a children's level.
MAX_MEAN_SENTENCE_WORDS = {
    ReadingLevel.AGE_6_8.value: 14.0,
    ReadingLevel.AGE_9_12.value: 21.0,
    ReadingLevel.TEEN.value: 28.0,
    ReadingLevel.ADULT.value: 40.0,
}


@dataclass(slots=True, frozen=True)
class Finding:
    severity: str
    kind: str
    message: str
    where: str = ""

    def __str__(self) -> str:
        loc = f" [{self.where}]" if self.where else ""
        return f"{self.severity.upper():7} {self.kind}{loc}: {self.message}"


class ContentValidator:
    """Validates one article payload against the pack it belongs to."""

    def __init__(
        self,
        known_sources: set[str] | None = None,
        known_media: set[str] | None = None,
        known_slugs: set[str] | None = None,
        known_types: set[str] | None = None,
        known_categories: set[str] | None = None,
    ) -> None:
        self.known_sources = known_sources or set()
        self.known_media = known_media or set()
        self.known_slugs = known_slugs or set()
        self.known_types = known_types or set()
        self.known_categories = known_categories or set()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _mean_sentence_words(text: str) -> float:
        stripped = re.sub(r"[#*_`>\[\]()|-]", " ", text)
        sentences = [s for s in re.split(r"[.!?]+", stripped) if s.strip()]
        if not sentences:
            return 0.0
        return sum(len(s.split()) for s in sentences) / len(sentences)

    # -- main entry point ------------------------------------------------

    def validate_article(self, data: dict[str, Any], where: str = "") -> list[Finding]:
        out: list[Finding] = []
        add = out.append
        loc = where or str(data.get("slug", "<unknown>"))

        # --- identity -----------------------------------------------------
        slug = data.get("slug", "")
        if not slug:
            add(Finding(ERROR, "missing_field", "slug is required", loc))
        elif not SLUG_RE.match(slug):
            add(Finding(ERROR, "bad_slug", f"slug {slug!r} must be lowercase-kebab-case", loc))
        if not data.get("title"):
            add(Finding(ERROR, "missing_field", "title is required", loc))

        type_key = data.get("type")
        if not type_key:
            add(Finding(ERROR, "missing_field", "type is required", loc))
        elif self.known_types and type_key not in self.known_types:
            add(Finding(ERROR, "unknown_type", f"unknown article type {type_key!r}", loc))

        # --- categories ---------------------------------------------------
        categories = data.get("categories") or []
        if not categories:
            add(Finding(WARNING, "no_category", "article has no category", loc))
        for cat in categories:
            if self.known_categories and cat not in self.known_categories:
                add(Finding(ERROR, "unknown_category", f"unknown category {cat!r}", loc))
        primary = data.get("primary_category")
        if primary and primary not in categories:
            add(
                Finding(
                    ERROR,
                    "bad_primary_category",
                    f"primary_category {primary!r} is not in categories",
                    loc,
                )
            )

        # --- reading levels -----------------------------------------------
        content = data.get("content") or {}
        if not isinstance(content, dict) or not content:
            add(Finding(ERROR, "no_content", "article has no content blocks", loc))
            content = {}

        for level in content:
            if level not in {lv.value for lv in READING_LEVELS}:
                add(Finding(ERROR, "bad_reading_level", f"unknown reading level {level!r}", loc))

        if ReadingLevel.ADULT.value not in content:
            add(
                Finding(
                    ERROR,
                    "missing_reading_level",
                    "the adult level is mandatory; it is the canonical text every "
                    "other level is derived from",
                    loc,
                )
            )

        for level, block in content.items():
            if not isinstance(block, dict):
                add(Finding(ERROR, "bad_content", f"content.{level} must be an object", loc))
                continue
            body = (block.get("body") or "").strip()
            summary = (block.get("summary") or "").strip()
            if not body:
                add(Finding(ERROR, "empty_body", f"content.{level}.body is empty", loc))
            if not summary:
                add(Finding(WARNING, "empty_summary", f"content.{level}.summary is empty", loc))
            ceiling = MAX_MEAN_SENTENCE_WORDS.get(level)
            if body and ceiling is not None:
                mean = self._mean_sentence_words(body)
                if mean > ceiling:
                    add(
                        Finding(
                            WARNING,
                            "reading_level_too_hard",
                            f"content.{level} averages {mean:.1f} words/sentence "
                            f"(ceiling {ceiling:.0f}); rewrite for this audience "
                            "rather than trimming the adult text",
                            loc,
                        )
                    )

        # Children's levels must not be a verbatim copy of a harder level.
        bodies = {lv: (blk or {}).get("body", "").strip() for lv, blk in content.items()}
        for kid_level in KIDS_LEVELS & set(bodies):
            for other, other_body in bodies.items():
                if other != kid_level and other_body and bodies[kid_level] == other_body:
                    add(
                        Finding(
                            ERROR,
                            "duplicated_reading_level",
                            f"content.{kid_level} is identical to content.{other}; "
                            "each level must be genuinely authored for its audience",
                            loc,
                        )
                    )

        # --- citations ------------------------------------------------------
        citations = data.get("citations") or []
        defined_markers: set[int] = set()
        for cit in citations:
            marker = cit.get("marker")
            if not isinstance(marker, int) or marker < 1:
                add(Finding(ERROR, "bad_citation", f"citation marker {marker!r} must be >= 1", loc))
                continue
            if marker in defined_markers:
                add(Finding(ERROR, "duplicate_citation", f"citation [{marker}] defined twice", loc))
            defined_markers.add(marker)

            src = cit.get("source")
            if not src:
                add(Finding(ERROR, "bad_citation", f"citation [{marker}] has no source", loc))
            elif self.known_sources and src not in self.known_sources:
                add(
                    Finding(
                        ERROR,
                        "unknown_source",
                        f"citation [{marker}] references unknown source {src!r}",
                        loc,
                    )
                )
            if not (cit.get("claim") or "").strip():
                add(
                    Finding(
                        ERROR,
                        "uncited_claim",
                        f"citation [{marker}] must state which claim it supports",
                        loc,
                    )
                )
            supports = cit.get("supports", "supports")
            if supports not in VALID_SUPPORTS:
                add(Finding(ERROR, "bad_citation", f"invalid supports={supports!r}", loc))

        used_markers: set[int] = set()
        for block in content.values():
            if isinstance(block, dict):
                used_markers |= {
                    int(m) for m in CITATION_MARKER_RE.findall(block.get("body") or "")
                }

        for missing in sorted(used_markers - defined_markers):
            add(
                Finding(
                    ERROR,
                    "dangling_citation",
                    f"body cites [{missing}] but no such citation is defined",
                    loc,
                )
            )
        for unused in sorted(defined_markers - used_markers):
            add(
                Finding(
                    INFO,
                    "unused_citation",
                    f"citation [{unused}] is defined but never referenced in any body",
                    loc,
                )
            )

        adult = content.get(ReadingLevel.ADULT.value) or {}
        if adult.get("body") and not defined_markers:
            add(
                Finding(
                    ERROR,
                    "missing_citation",
                    "a published article must cite at least one source",
                    loc,
                )
            )

        # --- facts ----------------------------------------------------------
        seen_fact_keys: set[str] = set()
        for fact in data.get("facts") or []:
            key = fact.get("key")
            if not key:
                add(Finding(ERROR, "bad_fact", "fact is missing a key", loc))
                continue
            if key in seen_fact_keys:
                add(Finding(ERROR, "duplicate_fact", f"fact {key!r} defined twice", loc))
            seen_fact_keys.add(key)
            if not fact.get("label"):
                add(Finding(ERROR, "bad_fact", f"fact {key!r} is missing a label", loc))
            if fact.get("value") in (None, ""):
                add(Finding(ERROR, "bad_fact", f"fact {key!r} has no value", loc))

            epistemic = fact.get("epistemic", "fact")
            try:
                status = Epistemic(epistemic)
            except ValueError:
                add(Finding(ERROR, "bad_epistemic", f"fact {key!r}: bad epistemic {epistemic!r}", loc))
                continue

            cites = fact.get("cite") or []
            if not isinstance(cites, list):
                add(Finding(ERROR, "bad_fact", f"fact {key!r}: cite must be a list of markers", loc))
                cites = []
            for marker in cites:
                if marker not in defined_markers:
                    add(
                        Finding(
                            ERROR,
                            "dangling_citation",
                            f"fact {key!r} cites [{marker}], which is not a defined citation",
                            loc,
                        )
                    )

            # The central rule: anything presented as established fact in the
            # quick-facts panel must be traceable to a source.
            if status is Epistemic.FACT and not cites:
                add(
                    Finding(
                        WARNING,
                        "missing_citation",
                        f"fact {key!r} is presented as established but cites no source; "
                        "add \"cite\": [n] or mark it as an estimate",
                        loc,
                    )
                )
            confidence = fact.get("confidence")
            if confidence is not None and not (0 <= float(confidence) <= 1):
                add(Finding(ERROR, "bad_fact", f"fact {key!r}: confidence must be 0..1", loc))
            if status is Epistemic.ESTIMATE and confidence is None:
                add(
                    Finding(
                        INFO,
                        "no_confidence",
                        f"fact {key!r} is an estimate without a confidence value",
                        loc,
                    )
                )

        # --- media ------------------------------------------------------------
        hero_count = 0
        for item in data.get("media") or []:
            uid = item.get("uid")
            if not uid:
                add(Finding(ERROR, "bad_media", "media entry has no uid", loc))
                continue
            if self.known_media and uid not in self.known_media:
                add(Finding(ERROR, "unknown_media", f"unknown media {uid!r}", loc))
            role = item.get("role", "inline")
            if role not in VALID_MEDIA_ROLES:
                add(Finding(ERROR, "bad_media", f"media {uid!r}: invalid role {role!r}", loc))
            if role == "hero":
                hero_count += 1
            # Accessibility is a hard requirement, not a nice-to-have.
            if not (item.get("alt") or "").strip():
                add(
                    Finding(
                        ERROR,
                        "missing_alt_text",
                        f"media {uid!r} has no alt text",
                        loc,
                    )
                )
        if hero_count > 1:
            add(Finding(ERROR, "bad_media", "article defines more than one hero image", loc))

        # --- relations ---------------------------------------------------------
        for rel in data.get("relations") or []:
            target = rel.get("to")
            kind = rel.get("kind", "related")
            if not target:
                add(Finding(ERROR, "bad_relation", "relation has no target", loc))
                continue
            if kind not in VALID_RELATION_KINDS:
                add(Finding(ERROR, "bad_relation", f"invalid relation kind {kind!r}", loc))
            if target == slug:
                add(Finding(ERROR, "bad_relation", "an article cannot relate to itself", loc))
            if self.known_slugs and target not in self.known_slugs:
                add(
                    Finding(
                        WARNING,
                        "orphan_relation",
                        f"relation points at {target!r}, which is not in this pack",
                        loc,
                    )
                )

        # --- kids safety --------------------------------------------------------
        if data.get("kids_safe", True) and (KIDS_LEVELS & set(content)):
            pass  # content offered to children; category-level gating happens at load
        elif not data.get("kids_safe", True) and (KIDS_LEVELS & set(content)):
            add(
                Finding(
                    ERROR,
                    "kids_safety",
                    "article is flagged kids_safe=false but provides children's "
                    "reading levels",
                    loc,
                )
            )

        return out


def worst_severity(findings: list[Finding]) -> str | None:
    for level in (ERROR, WARNING, INFO):
        if any(f.severity == level for f in findings):
            return level
    return None


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == ERROR for f in findings)
