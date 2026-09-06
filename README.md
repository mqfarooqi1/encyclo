# Modern Encarta / World Explorer

An offline-first, source-grounded educational encyclopaedia.

Every article names the sources behind its claims, distinguishes an established
fact from an estimate or a contested interpretation, is written independently at
four reading levels, and keeps a full append-only revision history. The whole
application runs locally with no internet connection and no cloud account.

> **Status:** the engine is complete and tested. 57 articles, each written at
> four reading levels and cited to authoritative sources.
> **Website:** [`site/`](site/) — a landing page with a download link,
> published to GitHub Pages by [`.github/workflows/pages.yml`](.github/workflows/pages.yml).

---

## Quick start

Requires **Python 3.11+** and nothing else. No Node, no build step, no
compilation, no third-party packages.

```bash
python run.py setup
```

```bash
python run.py serve
```

Then open <http://127.0.0.1:8000>.

`setup` runs the migrations, validates and loads the content packs, builds the
search index, scores article quality and runs the fact checker. It is safe to
re-run at any time.

---

## Why it is built this way

Most of the design follows from one decision: **the product must be trustworthy
before it is anything else.** Concretely:

| Principle | How it is enforced |
|---|---|
| No claim without evidence | The content validator refuses to load an article with no citations, or whose body cites a marker that does not exist. A published article with zero citations is a hard error. |
| Uncertainty is visible | Every structured fact carries an `epistemic` value — `fact`, `estimate`, `interpretation`, `opinion`, `uncertain`, `contested` — and anything that is not `fact` is badged in the UI. |
| Reading levels are authored, not truncated | The validator rejects a children's level that is byte-identical to a harder one, and warns when a children's level has adult sentence length. |
| AI cannot invent | The assistant only ever sees retrieved passages, and retrieval requires *every* salient query term to match. With no grounding, the model is never called at all. Citations the model emits are verified against the passages it was given, and fabricated ones are surfaced to the reader. |
| History cannot be rewritten | Revisions are append-only. An edit creates a new revision and repoints the article; nothing is updated in place. Migrations are checksummed and refuse to run if an applied file was edited. |
| Personal data stays personal | Bookmarks, notes and progress live in a physically separate SQLite file that content updates never touch. |

The trust chain the whole schema is organised around:

```
SOURCE → EVIDENCE → ARTICLE → CITATION → VERSION → REVIEW
```

---

## What is built

**Content and evidence**
- 34-table content schema with append-only revisions and full provenance
- Source catalogue with a 4-tier reliability ranking and explicit verification state
- Many-to-many fact↔citation model, so one source can support several facts honestly
- Media schema carrying licence, creator, attribution and redistributability

**Reading**
- Four independently authored reading levels per article, with graceful fallback
- Quick-facts panel with per-fact epistemic badges and citation links
- Inline citation markers that jump to a source entry stating the exact claim it supports
- Knowledge graph with pan/zoom exploration, and readable inverse relation labels
- Deep-time timeline spanning 4.5 billion years to the present
- Comparison mode built from shared `comparable_key` facts
- "How big?" scale strips, generated from any article carrying a comparable size fact
- Read-aloud at the reader's own level, using on-device speech — no network, no service

**Explorer Trails — quizzing as a journey**
- Two trails (ages 6–8 and 9–12) on a drawn board of 14 stations that unlock in sequence
- 22 quizzes, 125 questions across every category, each with a mandatory explanation
- Four question types: multiple choice, true/false, **ordering** and **matching**
- 18 badges awarded for finishing stations and trails, stored locally
- Stars (1–3) per station; replaying and doing worse never takes progress away
- Deliberately **no** streaks, daily targets or notifications — see below

**Search**
- SQLite FTS5 with prefix indexes, BM25 column weighting, and trust-weighted ranking
  (exact title → relevance → source quality → age fit — deliberately *not* popularity)
- Synonym expansion (`largest dinosaur`, `red planet`, `cavemen`, `pyramids`)
- Did-you-mean correction built from the index's own term dictionary, no external dictionary
- Hostile input can never reach FTS5 as syntax

**Operations**
- Forward-only checksummed migrations
- Quality scoring across 8 weighted components
- Automated fact checker for missing citations, dangling markers, broken sources,
  duplicate titles, unit inconsistencies and overdue reviews
- Editorial dashboard with issues, review queue and pack inventory
- Structured audit log of every content mutation

**Safety**
- Kids Mode: its own home page with fewer, larger choices, age-gated content,
  a forced children's reading level, and no unsupervised AI surface
- Strict CSP, no remote assets of any kind, path-traversal guard, secret-redacting logs
- AI provider abstraction: `none` (default), Anthropic, OpenAI, or a local model.
  Outbound network calls are refused unless explicitly enabled.

---

## Current state

**Complete and tested:** database, migrations, content pipeline, validation,
search, knowledge graph, timeline, quizzes, Explorer Trails, badges, learning
paths, comparison, reading levels, read-aloud, quality scoring, fact checking,
admin dashboard, HTTP API, frontend, AI grounding layer.
**137 tests, `ruff` and `mypy` clean.**

**Content:** 57 articles (228 individually written reading levels), 64 sources,
187 graph relations, 123 timeline events, 22 quizzes with 125 questions,
2 Explorer Trails with 14 stations, 18 badges, 5 learning paths. Every article
has all four reading levels and cited sources, and the pack validates with zero
errors and zero warnings.

Coverage spans space, dinosaurs, animals, the human body, science, history,
geography, countries, people, technology and the environment.

### A note on rewards

Badges are earned for *finishing* something. There are no streaks, no daily
goals, no notifications, and nothing that rewards returning tomorrow rather than
learning today. A child who has understood the material should have no reason to
be pulled back by the software. Replaying a station and scoring worse never
takes a star away, because punishing a second attempt discourages the exact
behaviour the product wants.

**Deliberately not done yet** — these are honest gaps, not hidden ones:

| Gap | Why |
|---|---|
| 57 articles, not thousands | Each is genuinely authored at four levels with real citations. Mass-producing thin stubs would violate the project's own trust rules — the validator rejects them. The pipeline scales; the writing is the cost. |
| No bundled imagery | The media *schema* is complete, but shipping images means verifying licences. Articles use generated covers rather than unverified third-party media. |
| Source links show "unverified" | Correct and intentional. A URL is only promoted to `verified` by the link checker, which needs network access (`ENCARTA_ALLOW_NETWORK=1`). |
| Maps show places, not vector basemaps | Place data and R-Tree spatial indexing are in place; an offline basemap needs a licensed tile set. |
| Update pipeline is schema + review queue | Proposal, diff, audit and approval tables exist and are enforced; the retrieval agent that generates proposals is not written. |
| No desktop packaging | The app is a local web app. Node/Tauri were unavailable in this environment; the JSON API boundary means a shell can be added without touching the engine. |

---

## Website and releases

`site/` holds a static landing page with a download link. It is deployed to
GitHub Pages by the `Publish site` workflow — enable it once under
**Settings → Pages → Source: GitHub Actions**.

`scripts/build_release.py` produces a versioned archive under `dist/`,
containing the source, content and documentation, and excluding the database,
personal data and caches:

```bash
python scripts/build_release.py
```

Attach the result to a GitHub release. The site's download link points at the
repository zipball, so it works whether or not a release exists.

## Commands

```bash
python run.py setup      # migrate, load, index, score, check
python run.py validate   # validate content packs without loading
python run.py load core  # load one pack
python run.py index      # rebuild the search index
python run.py score      # recompute quality scores
python run.py check      # run the automated fact checker
python run.py stats      # database statistics
python run.py serve      # run the application
```

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, data flow, stack rationale |
| [DATABASE.md](docs/DATABASE.md) | Schema, every table and why it exists |
| [CONTENT_GUIDE.md](docs/CONTENT_GUIDE.md) | Authoring articles and the validation rules |
| [SOURCE_POLICY.md](docs/SOURCE_POLICY.md) | Source tiers and verification |
| [AI_SAFETY.md](docs/AI_SAFETY.md) | Grounding guarantees and what the AI may not do |
| [OFFLINE_ARCHITECTURE.md](docs/OFFLINE_ARCHITECTURE.md) | Offline-first design and content packs |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, testing, conventions |
| [LICENSING.md](docs/LICENSING.md) | Content, media and code licensing |
| [ROADMAP.md](docs/ROADMAP.md) | Phase plan and current position |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | How to add content or code |

---

## Licence

Code: **Apache-2.0** (see `LICENSE`). Original article text: **CC BY-SA 4.0**.
Third-party sources are credited per article and are not redistributed —
this project stores bibliographic references, not source content.

This project takes inspiration from the *idea* of a rich offline educational
encyclopaedia. It contains no Microsoft Encarta content, code, imagery or
branding.
