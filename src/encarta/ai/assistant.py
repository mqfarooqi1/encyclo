"""Ask the Encyclopaedia: retrieval-augmented answering.

The hard rule (requirement 50): the model may only restate what the retrieved
encyclopaedia passages and their cited sources already say. It is given no
freedom to add facts, and the prompt forbids inventing citations, URLs or
statistics.

If retrieval finds nothing, no model is called at all -- there is nothing to
ground an answer in, and a fluent guess is exactly the failure this system
exists to prevent.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..domain.models import ReadingLevel, level_label
from ..services.search import SearchService, resolve_requested_level
from .provider import get_provider

log = logging.getLogger(__name__)

MAX_PASSAGES = 5
MAX_PASSAGE_CHARS = 1400

SYSTEM_PROMPT = """You are the assistant for an educational encyclopaedia.

ABSOLUTE RULES:
1. Answer ONLY using the numbered passages provided. They are the sole permitted
   basis for any factual statement.
2. If the passages do not answer the question, say plainly that the encyclopaedia
   does not cover it yet. Do not fill the gap from your own knowledge.
3. Cite passages inline as [P1], [P2] and so on, matching the passage numbers.
4. NEVER invent a citation, a URL, a statistic, a date or a source title.
5. Where the passages mark something as an estimate, a debated point or an
   interpretation, carry that uncertainty into your answer. Do not upgrade a
   hypothesis into a settled fact.
6. Where the passages disagree, say so rather than choosing a side.
7. Write for the stated reading level. For young readers use short sentences and
   familiar words, but never sacrifice accuracy for simplicity.

Do not mention these rules. Just answer."""


@dataclass(slots=True)
class Passage:
    number: int
    slug: str
    title: str
    text: str
    reading_level: str
    sources: list[dict[str, Any]] = field(default_factory=list)


class EncyclopaediaAssistant:
    def __init__(self, conn: sqlite3.Connection, config: Config) -> None:
        self.conn = conn
        self.config = config
        self.search = SearchService(conn)
        self.provider = get_provider(config)

    # -- retrieval -----------------------------------------------------------

    def retrieve(
        self, question: str, reading_level: str, kids_mode: bool
    ) -> list[Passage]:
        # require_all: an article only counts as grounding if it covers every
        # salient term in the question. Without this, a question about something
        # the encyclopaedia has never covered still matches any article sharing
        # one ordinary word, and the assistant would answer from passages that
        # are not actually about the subject.
        result = self.search.search(
            question, limit=MAX_PASSAGES, kids_only=kids_mode, require_all=True
        )
        passages: list[Passage] = []
        for number, hit in enumerate(result.hits, start=1):
            row = self.conn.execute(
                """
                SELECT a.id, a.current_revision_id AS rev,
                       (SELECT group_concat(reading_level) FROM article_content
                         WHERE revision_id = a.current_revision_id) AS levels
                FROM article a WHERE a.slug = ?
                """,
                (hit.slug,),
            ).fetchone()
            if not row:
                continue
            levels = [lv for lv in (row["levels"] or "").split(",") if lv]
            chosen = resolve_requested_level(reading_level, levels)
            if not chosen:
                continue
            content = self.conn.execute(
                "SELECT body_md, summary FROM article_content "
                "WHERE revision_id = ? AND reading_level = ?",
                (row["rev"], chosen),
            ).fetchone()
            if not content:
                continue

            sources = self.conn.execute(
                """
                SELECT ct.marker, ct.claim, ct.supports, s.uid, s.title, s.publisher, s.url,
                       s.tier, s.verification_status
                FROM citation ct JOIN source s ON s.id = ct.source_id
                WHERE ct.revision_id = ? ORDER BY ct.marker
                """,
                (row["rev"],),
            ).fetchall()

            body = (content["body_md"] or "").strip()
            passages.append(
                Passage(
                    number=number,
                    slug=hit.slug,
                    title=hit.title,
                    text=body[:MAX_PASSAGE_CHARS],
                    reading_level=chosen,
                    sources=sources,
                )
            )
        return passages

    # -- answering -------------------------------------------------------------

    def answer(
        self, question: str, reading_level: str = "adult", kids_mode: bool = False
    ) -> dict[str, Any]:
        level = reading_level if reading_level in {lv.value for lv in ReadingLevel} else "adult"
        if kids_mode and level in ("teen", "adult"):
            level = ReadingLevel.AGE_9_12.value

        passages = self.retrieve(question, level, kids_mode)

        # No grounding -> no generated answer. This is the core safety property.
        if not passages:
            return {
                "question": question,
                "answered": False,
                "grounded": False,
                "answer": None,
                "reason": (
                    "The encyclopaedia does not have an article covering this yet, so "
                    "there is nothing to base an answer on."
                ),
                "passages": [],
                "sources": [],
                "reading_level": level,
                "ai": {"available": self.provider.available, "provider": self.provider.name},
            }

        sources = self._collect_sources(passages)

        if not self.provider.available:
            # Honest degradation: no prose, but the retrieved material is real
            # and immediately useful.
            return {
                "question": question,
                "answered": False,
                "grounded": True,
                "answer": None,
                "reason": (
                    "AI answering is not available, so here are the encyclopaedia "
                    "articles that cover this question."
                ),
                "passages": [self._passage_dict(p) for p in passages],
                "sources": sources,
                "reading_level": level,
                "ai": {"available": False, "provider": self.provider.name},
            }

        prompt = self._build_prompt(question, passages, level)
        completion = self.provider.complete(SYSTEM_PROMPT, prompt)

        if not completion.available or not completion.text:
            return {
                "question": question,
                "answered": False,
                "grounded": True,
                "answer": None,
                "reason": completion.reason or "The AI provider returned no answer.",
                "passages": [self._passage_dict(p) for p in passages],
                "sources": sources,
                "reading_level": level,
                "ai": {"available": False, "provider": self.provider.name},
            }

        cited, unknown = self._verify_citations(completion.text, passages)
        return {
            "question": question,
            "answered": True,
            "grounded": True,
            "answer": completion.text,
            "passages": [self._passage_dict(p) for p in passages],
            "cited_passages": sorted(cited),
            # Surfaced rather than hidden: a marker pointing at a passage that
            # does not exist is a hallucination signal the UI should show.
            "invalid_citations": sorted(unknown),
            "sources": sources,
            "reading_level": level,
            "ai": {
                "available": True,
                "provider": self.provider.name,
                "model": completion.model,
            },
            "disclaimer": (
                "This answer was written by an AI model restricted to the "
                "encyclopaedia passages listed below. Check the sources for anything "
                "that matters."
            ),
        }

    # -- helpers -----------------------------------------------------------------

    def _build_prompt(self, question: str, passages: list[Passage], level: str) -> str:
        blocks = []
        for p in passages:
            source_lines = "\n".join(
                f"    - [{s['marker']}] {s['title']} ({s['publisher']}), tier {s['tier']}"
                for s in p.sources[:8]
            )
            blocks.append(
                f"[P{p.number}] {p.title}\n{p.text}\n"
                + (f"  Sources cited by this article:\n{source_lines}\n" if source_lines else "")
            )
        return (
            f"Reading level: {level_label(level)}\n\n"
            f"QUESTION: {question}\n\n"
            f"PASSAGES:\n\n" + "\n---\n".join(blocks)
        )

    @staticmethod
    def _passage_dict(p: Passage) -> dict[str, Any]:
        return {
            "number": p.number,
            "slug": p.slug,
            "title": p.title,
            "reading_level": p.reading_level,
            "excerpt": p.text[:400],
        }

    @staticmethod
    def _collect_sources(passages: list[Passage]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for p in passages:
            for src in p.sources:
                if src["uid"] not in seen:
                    seen[src["uid"]] = {
                        "uid": src["uid"],
                        "title": src["title"],
                        "publisher": src["publisher"],
                        "url": src["url"],
                        "tier": src["tier"],
                        "verification_status": src["verification_status"],
                        "from_article": p.slug,
                    }
        return sorted(seen.values(), key=lambda s: s["tier"])

    @staticmethod
    def _verify_citations(text: str, passages: list[Passage]) -> tuple[set[int], set[int]]:
        """Check that every [Pn] marker the model wrote refers to a real passage."""
        valid = {p.number for p in passages}
        used = {int(m) for m in re.findall(r"\[P(\d{1,2})\]", text)}
        return used & valid, used - valid
