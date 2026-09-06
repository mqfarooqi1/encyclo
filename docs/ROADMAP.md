# Roadmap

## Where the project is

| Phase | Status | Notes |
|---|---|---|
| 0 · Architecture and stack | **Done** | Python + SQLite chosen after evaluating the environment; see ARCHITECTURE.md |
| 1 · Application shell and UI | **Done** | Editorial design system, theme-aware, keyboard accessible, responsive |
| 2 · Database and article system | **Done** | 34 content tables, append-only revisions, 4 reading levels |
| 3 · Search | **Done** | FTS5, BM25 weighting, synonyms, did-you-mean, trust-weighted ranking |
| 4 · Categories and discovery | **Done** | Home, daily discovery, did-you-know, surprise-me, browse |
| 5 · Media | **Schema done, no assets** | Full licence model; no bitmaps shipped pending licence verification |
| 6 · Sources and citations | **Done** | Tiers, per-claim citations, fact↔citation many-to-many, verification state |
| 7 · Timeline | **Done** | Signed-year axis spanning 4.5 Ga to today, era filters |
| 8 · Maps | **Partial** | `place` + R-Tree indexing and place data; no offline basemap |
| 9 · Knowledge graph | **Done** | Typed relations, inverse labels, pan/zoom explorer |
| 10 · Kids Mode | **Done** | Own home page, age-gated content, forced reading level, restricted navigation, read-aloud |
| 11 · Quiz engine | **Done** | 16 quizzes, 89 questions, four question types; Explorer Trails with stations, stars and 15 badges |
| 12 · AI assistant | **Done** | Grounded RAG, citation verification, honest no-AI mode |
| 13 · Update pipeline | **Schema and review queue done** | Proposal/diff/audit tables enforced; generating agent not written |
| 14 · Offline content packs | **Loader done** | Multi-pack loading, versioning, inventory; no distribution format |
| 15 · Local AI | **Done** | Ollama-compatible provider, no key or internet needed |
| 16 · Admin CMS | **Read-only dashboard** | Stats, issues, review queue, packs; no editing UI |
| 17 · Testing, security, performance | **Done** | 135 tests, CSP, traversal guard, redacted logs, indexed queries |
| 18 · Packaging and distribution | **Not started** | Needs a desktop shell decision |

## Next, in order

**1 · Content to 100–300 articles.** The largest remaining gap and the one that
most changes how the product feels. The engine scales; authoring at four levels
with real citations is the cost. Priority: the remaining seed subjects (Roman
Empire, World War II, Australia, Pakistan, Newton, computers, the internet,
artificial intelligence, ocean life, the human body systems).

**2 · Source link verification.** A `verify-sources` command that checks each
URL with `ENCARTA_ALLOW_NETWORK=1`, records HTTP status, and moves sources out
of `unverified`. Small, self-contained, and removes the caveat currently shown
on every source.

**3 · Media ingest.** An importer for Wikimedia Commons, NASA and museum
open-access sets that refuses to import anything whose licence it cannot
determine, storing checksum and provenance per item.

**4 · The update pipeline agent.** The tables and review gates exist. What is
missing is the component that retrieves from approved sources, diffs against the
current revision, assigns confidence and files a proposal. It must never
publish — approval stays human, enforced by the schema.

**5 · Admin editing.** Turn the dashboard from read-only into a CMS: create and
edit articles, review proposals with a diff view, resolve issues, roll back
revisions.

**6 · Offline basemap.** Vector tiles from Natural Earth (public domain) so maps
work with no network.

**7 · Semantic search.** Populate `embedding_chunk` with a local model. Would
improve RAG recall, which the `AND` retrieval rule currently trades away for
safety.

**8 · Packaging.** A desktop shell. The JSON API boundary means this is additive
— Tauri, Electron or a PWA, whichever the environment supports.

## Deliberately deferred

Internationalisation beyond the architecture (no hard-coded strings in the data
layer), AR/VR, 3D models, teacher dashboards, student accounts, printable
worksheets. All are additive; none should shape the schema now.

## Things that must not change

- Revisions stay append-only.
- An AI proposal cannot become a revision without a named reviewer.
- Content and user data stay in separate database files.
- The application keeps working with no network and no AI provider.
- No media ships without a verified licence.
