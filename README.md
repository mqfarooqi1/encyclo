# Modern Encarta / World Explorer

An offline-first, source-grounded educational encyclopaedia.

Every article names the sources behind its claims, distinguishes an established
fact from an estimate or a contested interpretation, is written independently at
four reading levels, and keeps a full append-only revision history. The whole
application runs locally with no internet connection and no cloud account.

> **Download:** [get the app](https://github.com/mqfarooqi1/encyclo/archive/refs/heads/main.zip)
> · needs only Python 3.11+ · then `python run.py setup` and `python run.py serve`.
> Live at **<https://mqfarooqi1.github.io/encyclo/>**. The landing page lives in
> [`site/`](site/); the root [`index.html`](index.html) redirects to it so the
> site works with Pages set to *Deploy from a branch*. Setting Pages to
> *GitHub Actions* instead makes [`.github/workflows/pages.yml`](.github/workflows/pages.yml)
> publish `site/` at the root directly, and the redirect stops being used.

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

## Two tiers of content, kept visibly separate

The library has two kinds of article, and the app never blurs them.

**Authored** (`content/packs/core/`). Written for this project, four reading
levels each, cited claim by claim to the institution that produced the data —
NASA, USGS, the Smithsonian, the IUCN Red List, IPCC. Slow to produce and the
reason the project has a point of view.

**Imported** (`content/packs/wikipedia/`). Lead sections brought in from English
and Simple English Wikipedia under CC BY-SA 4.0, giving the two reading levels
from two genuinely different texts. Every imported article cites the exact
revision it came from, is recorded at source **tier 3** (a tertiary reference,
never tier 1), and carries a banner in the app saying it is imported rather than
written here.

Authored always wins: the importer is handed the slugs already in `core` and
refuses to produce an article for any of them. No text is paraphrased or
simplified by the importer — inventing sentences no source supports is the exact
failure this project exists to prevent.

**Kids Mode contains only authored articles.** An import is not marked kids-safe
and carries no children's reading band, because nobody has read it and the
harvest reaches into wars, battles, diseases and anatomy. The Simple English
text is offered at `teen`: it is written for readers with limited English, adult
learners included, rather than for children. A reviewer can promote an imported
article after reading it — the opposite default cannot be undone once a child
has seen the page.

```bash
ENCARTA_ALLOW_NETWORK=1 python run.py import-wikipedia
```

Network access is off by default and is needed only for this command; the
application itself never uses it.

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
**187 tests, `ruff` and `mypy` clean.**

**Content: 13,703 articles and 15,786 sources**, across fifteen categories —
space, dinosaurs, animals, the human body, science, history, geography,
countries, people, technology, the environment, arts, ideas, engineering and
mathematics. `setup` builds the whole thing from empty in about 19 seconds.

| | Authored | Imported | Total |
|---|---:|---:|---:|
| Articles | 57 | 13,646 | **13,703** |
| Sources | 64 | 15,722 | **15,786** |
| Reading levels written | 228 | — | — |
| In Kids Mode | 57 | 0 | **57** |

The 57 authored articles carry all four reading levels, structured facts with
epistemic labels, per-claim citations to tier-1 sources, 187 graph relations,
123 timeline events, 22 quizzes with 125 questions, 2 Explorer Trails with
14 stations, 18 badges and 5 learning paths. They score 81–95 for quality.

The 13,646 imported articles are lead sections under CC BY-SA 4.0, each citing
the exact revision it came from. 2,076 of them carry a second, independently
written reading level from Simple English Wikipedia. They score 39–62, because
they have no structured facts, no tier-1 citation and no quiz — and the score
says so rather than hiding it.

Both packs validate with **zero errors**. The 150 warnings are all
`reading_level_too_hard`: Wikipedia lead sections use long sentences, and the
validator says so instead of pretending otherwise.

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
| Only 57 articles are authored | The other 13,646 are imported reference text, labelled as such on every page and excluded from Kids Mode. Writing an article at four levels with per-claim citations is the cost; importing under a licence is the honest way to have a library as well. |
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
