"""Wikipedia importer.

Brings openly licensed reference text into the encyclopaedia at scale, which is
the only honest way to reach thousands of articles — hand-authoring four
reading levels per subject does not scale past a few dozen.

What this does and does not claim:

  * Imported articles are **not** original writing. They are Wikipedia lead
    sections, and every one carries a citation to the exact revision it came
    from, under CC BY-SA 4.0. The app shows that provenance rather than
    presenting the text as its own.
  * Two reading levels come from two genuinely different sources: the adult
    level from English Wikipedia, the 9-12 level from Simple English Wikipedia,
    which is written for readers with limited English. Where no Simple article
    exists, the article ships with the adult level only and says so.
  * No text is paraphrased, simplified or rewritten by this importer. Doing so
    would produce claims no source supports, which is the failure mode the whole
    project exists to avoid.

Network access is required and is refused unless ENCARTA_ALLOW_NETWORK=1.
Requests are batched, rate-limited and identified by User-Agent, per the
Wikimedia API etiquette guidelines.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ..config import Config

log = logging.getLogger(__name__)

USER_AGENT = (
    "ModernEncarta/0.1 (offline educational encyclopaedia; "
    "+https://github.com/mqfarooqi1/encyclo)"
)
EN = "en.wikipedia.org"
SIMPLE = "simple.wikipedia.org"

# Wikimedia caps extracts at 20 titles per request.
EXTRACT_BATCH = 20
# Courtesy delay between requests. The API permits more, but there is no reason
# to push it for a one-off import.
DELAY_SECONDS = 0.12
MAX_RETRIES = 4

#: Reading level the Simple English text is offered at. See _article().
SIMPLE_LEVEL = "teen"

#: Wikipedia's own inline reference superscripts, which survive `explaintext`
#: on some pages: "[2]", "[17]", "[citation needed]", "[note 3]".
#:
#: Deliberately numeric-plus-named, not "[a]"-style letters. Our citation
#: markers are numeric, so a surviving "[a]" is not a false link and stripping
#: it would only risk eating real content — "the array index [i]", "[sic]".
#: The cleaner should remove exactly what would otherwise become a lie.
_WIKI_REF_RE = re.compile(
    r"\[(?:\d{1,3}|citation needed|clarification needed|note \d{1,3})\]",
    re.IGNORECASE,
)
_STRANDED_SPACE_RE = re.compile(r"[ \t]+([.,;:!?])")
_RUN_OF_SPACES_RE = re.compile(r"[ \t]{2,}")


def strip_reference_markers(text: str) -> str:
    """Remove Wikipedia's own reference superscripts from an extract.

    These must not survive into an article body. In this schema ``[n]`` *is* a
    citation link, so a stray "[2]" inherited from Wikipedia's reference list
    renders as a citation this article does not have — pointing at nothing, or
    worse, at whichever source happens to occupy that number. Shipping a
    citation link that leads somewhere the text never claimed is exactly the
    failure the validator, the epistemic labels and the grounded assistant all
    exist to prevent, and it would arrive here by pure omission.

    Runs before our own marker is attached, so it never eats that.
    """
    cleaned = _WIKI_REF_RE.sub("", text)
    # Removing a superscript can strand a space before punctuation, or leave a
    # double space mid-sentence.
    return _STRANDED_SPACE_RE.sub(r"\1", _RUN_OF_SPACES_RE.sub(" ", cleaned))


MIN_EXTRACT_CHARS = 220
MAX_EXTRACT_CHARS = 6000

# Titles that are navigational or meta rather than encyclopaedic subjects.
_SKIP_TITLE = re.compile(
    r"^(List of|Lists of|Index of|Outline of|Timeline of|Glossary of|"
    r"Comparison of|Bibliography of|Category:|Template:|Portal:|Draft:|"
    r"Wikipedia:|Help:|File:|Module:)",
    re.IGNORECASE,
)
_SKIP_SUFFIX = re.compile(r"\((disambiguation|surname|given name|name)\)$", re.IGNORECASE)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """Title -> lowercase-kebab slug matching the content validator's rule."""
    text = unicodedata.normalize("NFKD", title)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("&", " and ")
    return _SLUG_STRIP.sub("-", text.lower()).strip("-")


@dataclass(slots=True)
class Subject:
    """One harvest root: a Wikipedia category mapped onto our taxonomy."""

    category: str
    encarta_category: str
    article_type: str
    depth: int = 1
    cap: int = 400


@dataclass(slots=True)
class ImportReport:
    titles_seen: int = 0
    fetched: int = 0
    written: int = 0
    skipped_short: int = 0
    skipped_duplicate: int = 0
    skipped_missing: int = 0
    simple_levels: int = 0
    requests: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.written} articles written "
            f"({self.simple_levels} with a Simple English level) from "
            f"{self.titles_seen} candidate titles in {self.requests} requests · "
            f"skipped {self.skipped_duplicate} duplicate, "
            f"{self.skipped_short} too short, {self.skipped_missing} missing"
        )


class WikipediaClient:
    """Minimal, polite MediaWiki API client built on urllib (no dependencies)."""

    def __init__(self, config: Config) -> None:
        if not config.allow_network:
            raise PermissionError(
                "Wikipedia import needs network access. Set ENCARTA_ALLOW_NETWORK=1 "
                "to allow it; the application itself never requires the network."
            )
        self.requests = 0
        self._last_call = 0.0

    def call(self, host: str, **params: Any) -> dict[str, Any]:
        params.setdefault("format", "json")
        params.setdefault("formatversion", "2")
        url = f"https://{host}/w/api.php?" + urllib.parse.urlencode(params)

        for attempt in range(MAX_RETRIES):
            elapsed = time.monotonic() - self._last_call
            if elapsed < DELAY_SECONDS:
                time.sleep(DELAY_SECONDS - elapsed)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    self.requests += 1
                    self._last_call = time.monotonic()
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                self._last_call = time.monotonic()
                if attempt == MAX_RETRIES - 1:
                    raise
                backoff = 2 ** attempt
                log.warning("api error (%s), retrying in %ds", type(exc).__name__, backoff)
                time.sleep(backoff)
        return {}

    # -- title harvesting ---------------------------------------------------

    def category_titles(self, category: str, depth: int, cap: int) -> list[str]:
        """Breadth-first walk of a category tree, returning article titles."""
        seen: set[str] = set()
        out: list[str] = []
        frontier = [category if category.startswith("Category:") else f"Category:{category}"]

        for level in range(depth + 1):
            next_frontier: list[str] = []
            for cat in frontier:
                if len(out) >= cap:
                    break
                for title, is_category in self._members(cat):
                    if is_category:
                        if level < depth:
                            next_frontier.append(title)
                        continue
                    if title in seen or _SKIP_TITLE.match(title) or _SKIP_SUFFIX.search(title):
                        continue
                    seen.add(title)
                    out.append(title)
                    if len(out) >= cap:
                        break
            frontier = next_frontier
            if not frontier or len(out) >= cap:
                break
        return out[:cap]

    def _members(self, category: str) -> Iterator[tuple[str, bool]]:
        cont: dict[str, Any] = {}
        for _ in range(20):  # bounded paging
            data = self.call(
                EN, action="query", list="categorymembers", cmtitle=category,
                cmlimit=500, cmtype="page|subcat", **cont,
            )
            for member in data.get("query", {}).get("categorymembers", []):
                yield member["title"], member.get("ns") == 14
            if "continue" not in data:
                return
            cont = data["continue"]

    # -- content ------------------------------------------------------------

    def extracts(self, host: str, titles: list[str]) -> dict[str, dict[str, Any]]:
        """Lead-section plain text plus metadata, keyed by title."""
        out: dict[str, dict[str, Any]] = {}
        data = self.call(
            host, action="query", prop="extracts|info|revisions|pageprops",
            exintro=1, explaintext=1, exsectionformat="plain",
            inprop="url", rvprop="ids", titles="|".join(titles), redirects=1,
        )
        query = data.get("query", {})
        # Follow redirects back to the requested title so callers can match.
        redirects = {r["to"]: r["from"] for r in query.get("redirects", [])}
        for page in query.get("pages", []):
            if page.get("missing"):
                continue
            title = page.get("title", "")
            extract = (page.get("extract") or "").strip()
            if not extract:
                continue
            revisions = page.get("revisions") or [{}]
            out[title] = {
                "title": title,
                "requested_as": redirects.get(title, title),
                "pageid": page.get("pageid"),
                "revid": revisions[0].get("revid"),
                "url": page.get("fullurl"),
                "description": (page.get("pageprops") or {}).get("wikibase-shortdesc", ""),
                "extract": extract[:MAX_EXTRACT_CHARS],
            }
        return out


# ---------------------------------------------------------------------------
# The harvest plan. Each root maps a Wikipedia category onto one of our own
# categories and article types, so imported articles land in the right place in
# the navigation rather than in an undifferentiated heap.
# ---------------------------------------------------------------------------

PLAN: tuple[Subject, ...] = (
    # --- space
    Subject("Planets", "space", "planet", depth=1, cap=120),
    Subject("Moons", "space", "astronomical_object", depth=1, cap=180),
    Subject("Constellations", "space", "astronomical_object", depth=0, cap=100),
    Subject("Stars", "space", "astronomical_object", depth=1, cap=220),
    Subject("Galaxies", "space", "astronomical_object", depth=1, cap=160),
    Subject("Space missions", "space", "historical_event", depth=1, cap=260),
    Subject("Astronomical objects", "space", "astronomical_object", depth=1, cap=200),
    # --- prehistory
    Subject("Dinosaurs", "dinosaurs", "dinosaur", depth=2, cap=700),
    Subject("Prehistoric mammals", "dinosaurs", "animal", depth=2, cap=300),
    Subject("Geological periods", "dinosaurs", "science_concept", depth=1, cap=120),
    Subject("Fossils", "dinosaurs", "science_concept", depth=1, cap=150),
    # --- animals and plants
    Subject("Mammals", "animals", "animal", depth=2, cap=700),
    Subject("Birds", "animals", "animal", depth=2, cap=500),
    Subject("Reptiles", "animals", "animal", depth=2, cap=300),
    Subject("Fish", "animals", "animal", depth=2, cap=300),
    Subject("Insects", "animals", "animal", depth=2, cap=300),
    Subject("Marine biology", "animals", "animal", depth=1, cap=200),
    Subject("Trees", "environment", "plant", depth=2, cap=250),
    Subject("Flowering plants", "environment", "plant", depth=1, cap=200),
    # --- human body and medicine
    Subject("Human anatomy", "human-body", "body_system", depth=2, cap=400),
    Subject("Organs (anatomy)", "human-body", "body_system", depth=1, cap=150),
    Subject("Human physiology", "human-body", "body_system", depth=1, cap=200),
    Subject("Infectious diseases", "human-body", "medical", depth=1, cap=250),
    Subject("Nutrition", "human-body", "medical", depth=1, cap=150),
    # --- science
    Subject("Chemical elements", "science", "science_concept", depth=0, cap=130),
    Subject("Physical quantities", "science", "science_concept", depth=1, cap=180),
    Subject("Branches of physics", "science", "science_concept", depth=1, cap=200),
    Subject("Chemistry", "science", "science_concept", depth=1, cap=250),
    Subject("Biology", "science", "science_concept", depth=1, cap=250),
    Subject("Genetics", "science", "science_concept", depth=1, cap=180),
    Subject("Evolutionary biology", "science", "science_concept", depth=1, cap=180),
    Subject("Minerals", "science", "science_concept", depth=1, cap=250),
    # --- geography and environment
    Subject("Landforms", "geography", "place", depth=2, cap=400),
    Subject("Mountains", "geography", "place", depth=2, cap=300),
    Subject("Rivers", "geography", "place", depth=2, cap=300),
    Subject("Deserts", "geography", "place", depth=1, cap=150),
    Subject("Volcanoes", "geography", "place", depth=2, cap=250),
    Subject("Oceans", "geography", "place", depth=1, cap=120),
    Subject("Natural disasters", "environment", "environment_topic", depth=1, cap=200),
    Subject("Climate", "environment", "environment_topic", depth=1, cap=200),
    Subject("Ecology", "environment", "environment_topic", depth=1, cap=200),
    Subject("Biomes", "environment", "environment_topic", depth=1, cap=120),
    # --- countries and places
    Subject("Countries in Europe", "countries", "country", depth=0, cap=80),
    Subject("Countries in Asia", "countries", "country", depth=0, cap=80),
    Subject("Countries in Africa", "countries", "country", depth=0, cap=80),
    Subject("Countries in North America", "countries", "country", depth=0, cap=60),
    Subject("Countries in South America", "countries", "country", depth=0, cap=40),
    Subject("Countries in Oceania", "countries", "country", depth=0, cap=40),
    Subject("Capitals in Europe", "countries", "city", depth=0, cap=80),
    Subject("Capitals in Asia", "countries", "city", depth=0, cap=80),
    Subject("Capitals in Africa", "countries", "city", depth=0, cap=80),
    # --- history
    Subject("Ancient civilizations", "history", "civilisation", depth=2, cap=300),
    Subject("Wars by type", "history", "war", depth=2, cap=300),
    Subject("Historical eras", "history", "historical_event", depth=1, cap=150),
    Subject("Empires", "history", "civilisation", depth=2, cap=300),
    Subject("Archaeological sites", "history", "place", depth=2, cap=300),
    Subject("Revolutions", "history", "historical_event", depth=1, cap=180),
    # --- people
    Subject("Physicists", "people", "scientist", depth=1, cap=350),
    Subject("Chemists", "people", "scientist", depth=1, cap=250),
    Subject("Biologists", "people", "scientist", depth=1, cap=250),
    Subject("Mathematicians", "people", "scientist", depth=1, cap=300),
    Subject("Astronomers", "people", "scientist", depth=1, cap=250),
    Subject("Inventors", "people", "person", depth=1, cap=300),
    Subject("Explorers", "people", "person", depth=1, cap=250),
    Subject("Philosophers", "ideas", "person", depth=1, cap=300),
    # --- technology
    Subject("Computer science", "technology", "technology", depth=1, cap=300),
    Subject("Inventions", "technology", "invention", depth=2, cap=350),
    Subject("Engineering disciplines", "engineering", "engineering_concept", depth=1, cap=180),
    Subject("Machines", "engineering", "technology", depth=2, cap=250),
    Subject("Transport", "technology", "technology", depth=1, cap=250),
    # --- maths, arts, ideas
    Subject("Mathematical concepts", "maths", "math_concept", depth=2, cap=350),
    Subject("Theorems", "maths", "math_concept", depth=2, cap=250),
    Subject("Geometry", "maths", "math_concept", depth=1, cap=200),
    Subject("Musical instruments", "arts", "artwork", depth=2, cap=250),
    Subject("Art movements", "arts", "artwork", depth=1, cap=150),
    Subject("Literary genres", "arts", "book", depth=1, cap=150),
    Subject("Languages", "arts", "language", depth=1, cap=250),
    Subject("Religions", "ideas", "religion", depth=1, cap=180),
    Subject("Philosophical concepts", "ideas", "idea", depth=2, cap=300),
)


class WikipediaImporter:
    def __init__(self, config: Config, exclude_slugs: Iterable[str] = ()) -> None:
        self.config = config
        self.client = WikipediaClient(config)
        self.exclude = set(exclude_slugs)
        self.report = ImportReport()

    # -- harvesting ---------------------------------------------------------

    def harvest(self, plan: Iterable[Subject] = PLAN) -> dict[str, Subject]:
        """Collect candidate titles, remembering which subject each came from."""
        chosen: dict[str, Subject] = {}
        for subject in plan:
            try:
                titles = self.client.category_titles(subject.category, subject.depth, subject.cap)
            except Exception as exc:
                self.report.errors.append(f"{subject.category}: {type(exc).__name__}")
                log.warning("category %s failed: %s", subject.category, exc)
                continue
            added = 0
            for title in titles:
                if title in chosen:
                    continue
                if slugify(title) in self.exclude:
                    self.report.skipped_duplicate += 1
                    continue
                chosen[title] = subject
                added += 1
            log.info("%-34s %4d titles (%d new)", subject.category, len(titles), added)
        self.report.titles_seen = len(chosen)
        return chosen

    # -- building -----------------------------------------------------------

    def _article(
        self, subject: Subject, en: dict[str, Any], simple: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        title = en["title"]
        slug = slugify(title)
        if not slug or slug in self.exclude:
            return None

        body = self._to_body(en["extract"])
        if len(body) < MIN_EXTRACT_CHARS:
            self.report.skipped_short += 1
            return None

        summary = en.get("description") or self._first_sentence(en["extract"])
        content = {
            "adult": {
                "summary": summary,
                # The citation marker is attached to the opening paragraph so the
                # reader sees immediately where the whole text came from.
                "body": self._cite_first_paragraph(body),
            }
        }

        if simple:
            simple_body = self._to_body(simple["extract"])
            if len(simple_body) >= MIN_EXTRACT_CHARS and simple_body != body:
                # `teen`, not `age9_12`. Simple English Wikipedia is written for
                # readers with limited English — adult learners included — not
                # specifically for children, and claiming a children's band on
                # text nobody has reviewed is the same unearned claim as marking
                # it kids_safe. The validator enforces the pairing: a kids band
                # on a kids_safe=false article is an error, and rightly so.
                content[SIMPLE_LEVEL] = {
                    "summary": self._first_sentence(simple["extract"]),
                    "body": self._cite_first_paragraph(simple_body, marker=2),
                }
                self.report.simple_levels += 1

        citations = [{
            "marker": 1,
            "source": f"wikipedia-en-{en['pageid']}",
            "claim": f"Article text for {title}, from the English Wikipedia revision cited.",
            "supports": "supports",
        }]
        if SIMPLE_LEVEL in content:
            citations.append({
                "marker": 2,
                "source": f"wikipedia-simple-{simple['pageid']}",  # type: ignore[index]
                "claim": f"Simplified article text for {title}, from Simple English Wikipedia.",
                "supports": "supports",
            })

        return {
            "slug": slug,
            "title": title,
            "type": subject.article_type,
            "categories": [subject.encarta_category],
            "primary_category": subject.encarta_category,
            "summary": summary[:400],
            # Not kids-safe, and this is deliberate. Kids Mode is a *vetted*
            # subset, and nobody has read these. The harvest spans wars,
            # battles, diseases and human anatomy; marking the lot safe because
            # it imported cleanly would be exactly the unearned claim the rest
            # of this project exists to refuse. A reviewer can promote an
            # imported article to kids_safe after reading it — the reverse
            # default cannot be undone once a child has seen the page.
            "kids_safe": False,
            "content": content,
            "citations": citations,
            "review": {"last_reviewed": date.today().isoformat(), "review_months": 12},
            "change_reason": "Imported from Wikipedia under CC BY-SA 4.0",
        }

    def _sources(self, records: list[tuple[dict[str, Any], dict[str, Any] | None]]) -> list[dict[str, Any]]:
        """One source record per imported article, pinned to the exact revision.

        CC BY-SA attribution requires crediting the authors; linking the specific
        revision is the standard way to do that, since the revision history names
        them.
        """
        today = date.today().isoformat()
        out: list[dict[str, Any]] = []
        for en, simple in records:
            out.append({
                "uid": f"wikipedia-en-{en['pageid']}",
                "title": f"{en['title']} — Wikipedia",
                "publisher": "Wikipedia contributors",
                "type": "encyclopaedia",
                "tier": 3,
                "url": f"https://en.wikipedia.org/w/index.php?curid={en['pageid']}&oldid={en['revid']}",
                "accessed": today,
                "license": "CC BY-SA 4.0",
                "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                "notes": "Tertiary source. Follow the article's own references for primary evidence.",
            })
            if simple:
                out.append({
                    "uid": f"wikipedia-simple-{simple['pageid']}",
                    "title": f"{simple['title']} — Simple English Wikipedia",
                    "publisher": "Wikipedia contributors",
                    "type": "encyclopaedia",
                    "tier": 3,
                    "url": (
                        f"https://simple.wikipedia.org/w/index.php?"
                        f"curid={simple['pageid']}&oldid={simple['revid']}"
                    ),
                    "accessed": today,
                    "license": "CC BY-SA 4.0",
                    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                })
        return out

    @staticmethod
    def _to_body(extract: str) -> str:
        extract = strip_reference_markers(extract)
        paragraphs = [p.strip() for p in extract.split("\n") if p.strip()]
        # Drop pronunciation/etymology fragments that read badly out of context.
        cleaned = [p for p in paragraphs if len(p) > 40]
        return "\n\n".join(cleaned)

    @staticmethod
    def _cite_first_paragraph(body: str, marker: int = 1) -> str:
        parts = body.split("\n\n")
        parts[0] = f"{parts[0]} [{marker}]"
        return "\n\n".join(parts)

    @staticmethod
    def _first_sentence(text: str) -> str:
        # Summaries are read straight from the extract, so they need the same
        # cleaning as bodies — a "[2]" in a summary is the same false link.
        text = strip_reference_markers(text)
        match = re.search(r"^(.{40,320}?[.!?])(\s|$)", text.replace("\n", " "))
        return match.group(1).strip() if match else text[:200].strip()

    # -- run ----------------------------------------------------------------

    def run(self, out_dir: Path, plan: Iterable[Subject] = PLAN,
            limit: int | None = None) -> ImportReport:
        chosen = self.harvest(plan)
        titles = list(chosen)[:limit] if limit else list(chosen)
        log.info("fetching %d articles", len(titles))

        out_dir.mkdir(parents=True, exist_ok=True)
        articles: list[dict[str, Any]] = []
        records: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

        for index in range(0, len(titles), EXTRACT_BATCH):
            batch = titles[index:index + EXTRACT_BATCH]
            try:
                en_pages = self.client.extracts(EN, batch)
                simple_pages = self.client.extracts(SIMPLE, batch)
            except Exception as exc:
                self.report.errors.append(f"batch at {index}: {type(exc).__name__}")
                continue

            for title in batch:
                en = en_pages.get(title)
                if not en:
                    self.report.skipped_missing += 1
                    continue
                self.report.fetched += 1
                simple = simple_pages.get(title)
                article = self._article(chosen[title], en, simple)
                if article is None:
                    continue
                # Guard against two Wikipedia titles collapsing to one slug.
                if article["slug"] in self.exclude:
                    self.report.skipped_duplicate += 1
                    continue
                self.exclude.add(article["slug"])
                articles.append(article)
                records.append((en, simple if SIMPLE_LEVEL in article["content"] else None))

            if (index // EXTRACT_BATCH) % 25 == 0:
                log.info("  %d/%d titles · %d articles", min(index + EXTRACT_BATCH, len(titles)),
                         len(titles), len(articles))

        self._write(out_dir, articles, self._sources(records))
        self.report.written = len(articles)
        self.report.requests = self.client.requests
        return self.report

    def _write(self, out_dir: Path, articles: list[dict[str, Any]],
               sources: list[dict[str, Any]]) -> None:
        """Write the pack. Articles go to a single gzipped JSONL file rather than
        thousands of loose files, which keeps the repository and the download
        manageable."""
        (out_dir / "pack.json").write_text(json.dumps({
            "key": "wikipedia",
            "version": date.today().strftime("%Y.%m"),
            "title": "Wikipedia Reference Pack",
            "description": (
                "Lead sections imported from English and Simple English Wikipedia "
                "under CC BY-SA 4.0. Each article cites the exact revision it came "
                "from. This is imported reference text, not original writing."
            ),
            "language": "en",
            "license": "CC-BY-SA-4.0",
            "attribution": (
                "Text from Wikipedia, by Wikipedia contributors, licensed CC BY-SA 4.0. "
                "Each article links the specific revision used, whose history names "
                "the authors."
            ),
        }, indent=2) + "\n", encoding="utf-8")

        # One source per imported article, so this runs to tens of thousands of
        # records. Compressed, because the alternative is a multi-megabyte JSON
        # file in version control that nobody will ever read as text.
        with gzip.open(out_dir / "sources.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(sources, handle, ensure_ascii=False)

        with gzip.open(out_dir / "articles.jsonl.gz", "wt", encoding="utf-8") as handle:
            for article in articles:
                handle.write(json.dumps(article, ensure_ascii=False) + "\n")
