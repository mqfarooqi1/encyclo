# Architecture

## Stack, and why

The environment this was built for had **Python 3.14 and Git, and no Node.js,
npm or Rust**. That single fact decided the stack, and the project brief
explicitly asked for the recommended stack to be evaluated rather than followed.

What Python 3.14 ships with turned out to be an unusually good fit:

| Capability | Provided by | Used for |
|---|---|---|
| Full-text search with ranking | SQLite FTS5 + `bm25()` | Article search |
| Prefix indexes | FTS5 `prefix='2 3 4'` | As-you-type autocomplete |
| Term dictionary | `fts5vocab` | Did-you-mean, with no shipped dictionary |
| Spatial indexing | R-Tree | Map viewport and proximity queries |
| Structured columns | JSON1 | Fact schemas, diffs, audit detail |
| Web server | WSGI + `wsgiref` | HTTP layer |

**Chosen:** Python + SQLite core, dependency-free WSGI HTTP layer, zero-build
ES-module frontend.

**Rejected, with reasons:**

- *React + Vite + Electron/Tauri* — needs Node and Rust, neither installed.
  Would have meant the app could not run at all on the target machine.
- *FastAPI + uvicorn* — pleasant, but adds dependencies to something intended
  to run offline on a child's machine. The stdlib WSGI path costs little and
  removes an entire class of supply-chain and upgrade risk.
- *A Markdown library* — a third-party parser is a real HTML-injection surface.
  The article format uses a fixed small subset, so it is rendered directly to
  DOM nodes instead (`static/js/markdown.js`). Nothing in the frontend ever
  turns a database string into HTML.

**The escape hatch:** the frontend talks to the backend exclusively over a JSON
HTTP API. A React or Tauri shell can be added later without touching the engine,
which is roughly 70% of the code. Nothing about that choice is load-bearing.

---

## Layers

```
                 ┌─────────────────────────────────────────┐
   browser  ───► │  web/static  — zero-build ES modules    │
                 │  app.js · views.js · api.js · dom.js    │
                 └────────────────┬────────────────────────┘
                                  │  JSON over HTTP (same origin)
                 ┌────────────────▼────────────────────────┐
                 │  web/  — WSGI app, router, security     │
                 │  app.py (routing, CSP, traversal guard) │
                 │  api.py (endpoints)                     │
                 └────────────────┬────────────────────────┘
                                  │
      ┌───────────────────────────┼───────────────────────────┐
      │                           │                           │
┌─────▼─────────┐        ┌────────▼────────┐        ┌─────────▼────────┐
│ repositories/ │        │   services/     │        │      ai/         │
│ reads only    │        │ search, quality │        │ provider + RAG   │
│ articles.py   │        │ fact checking   │        │ assistant.py     │
│ discovery.py  │        │                 │        │                  │
└─────┬─────────┘        └────────┬────────┘        └─────────┬────────┘
      │                           │                           │
      └───────────────────────────┼───────────────────────────┘
                                  │
                 ┌────────────────▼────────────────────────┐
                 │  db/  — connection pool, migrations     │
                 └────────────────┬────────────────────────┘
                                  │
              ┌───────────────────┴───────────────────┐
              │                                       │
     ┌────────▼─────────┐                   ┌─────────▼────────┐
     │ encarta-content  │                   │  encarta-user    │
     │ articles, sources│    ATTACH "usr"   │ bookmarks, notes │
     │ media, index     │◄─────────────────►│ progress         │
     │ REPLACEABLE      │                   │ NEVER OVERWRITTEN│
     └──────────────────┘                   └──────────────────┘
                    ▲
                    │  validated ingest
        ┌───────────┴────────────┐
        │  content/              │
        │  validate.py → loader  │
        └───────────┬────────────┘
                    │
        ┌───────────▼────────────┐
        │  content/packs/core/   │
        │  JSON article sources  │
        └────────────────────────┘
```

### Layer rules

- **Repositories read; they never write.** Every write goes through the loader
  or the pipeline, so there is exactly one path by which trusted content can
  change, and it is audited.
- **Repositories only ever read `article.current_revision_id`.** A draft or a
  superseded revision is invisible to the reader-facing app by construction, not
  by a filter someone might forget.
- **The AI layer has no database write access.** It can retrieve and it can
  propose; only a named human reviewer can turn a proposal into a revision, and
  the schema enforces that with a `CHECK` constraint.

---

## The two databases

This is the single most consequential structural decision.

`encarta-content.db` holds articles, sources, media and the search index. It is
replaceable — a content pack update can drop and rebuild it.

`encarta-user.db` holds bookmarks, notes, highlights, reading progress and quiz
attempts. It is never shipped and never overwritten.

They are attached to one connection (`usr`), so a single query can join *"the
articles I bookmarked"* without a second round trip, while remaining separate
files on disk.

There is a real trap here, and the tests pin it. `sqlite3.executescript()`
cannot be pointed at an attached schema: an unqualified `CREATE TABLE` always
lands in `main`. Migrating the user schema through the ATTACH silently builds
the personal-data tables *inside the content database*, which would mean a
content update destroys the user's notes. The user database therefore gets its
own short-lived connection during migration, and
`test_user_data_lives_in_a_separate_database` asserts no leakage.

---

## Request lifecycle

1. `WSGIApp.__call__` — catches everything, attaches security headers.
2. `/api/*` → `Router.resolve` → handler; anything else → static file, with a
   path-traversal guard resolving against the static root.
3. Unknown non-API paths return the app shell, so deep links survive a reload.
4. Handlers use a thread-local SQLite connection (the WSGI server is threaded
   and SQLite connections are not thread-safe).
5. Responses are JSON with `Cache-Control: no-store` by default.

---

## Search ranking

Lexical relevance alone would rank a passing mention above an authoritative
article. The final score blends five signals:

```
score = -bm25(weighted columns)      # lexical relevance
      + 100  if title == query        # exact title wins outright
      +  40  if title startswith query
      +  15  if all terms in title
      +  25  if the article matches EVERY query term
      + 3 × mean(5 - source_tier)     # better-sourced articles rank higher
      + quality_score / 20            # editorial completeness
```

Column weights are `title 12, aliases 9, summary 4, body 1, facts 2.5,
categories 2` — a title hit should beat a passing mention in a long body.

Ranking is deliberately **not** influenced by view counts. Popularity is not
evidence.

**Titles are compared with any leading `the`/`a`/`an` removed.** Otherwise "The
Moon" earns neither the exact-title nor the prefix bonus for the query *moon*,
and every short article merely starting with the word outranks it. With 57
articles nothing started with "moon"; with 13,646 imported ones, *Moondial*,
*Moonlet* and *Moon Duchin* all did, and the encyclopaedia's own Moon article
fell off the first page entirely.

**Coverage is scored, because OR matching alone answers the wrong question.**
Browsing search matches with `OR` so a partial match still surfaces. But a
strong hit on one rare word then beats an article answering the whole query:
*what killed the dinosaurs* returned a biography of someone who was killed,
because "killed" is rarer than "dinosaurs" and bm25 rewards rarity. A second
indexed `AND` query says which articles contain every term, and those get +25 —
below the title bonuses, well above the few points that separate raw bm25
scores.

Two subtleties are worth stating, because both were bugs here first.

SQL orders by `bm25` alone, so the results must be re-sorted in Python after the
trust signals are folded in. Skipping that step leaves the extra signals
computed but inert — `test_results_are_ordered_by_final_score_not_raw_bm25`
now prevents it.

Re-ranking can only reorder rows SQL actually returned, so the candidate pool
must be wider than the page: `POOL_FACTOR × limit`, capped at `MAX_POOL`, then
sliced in Python. When the pool equalled the page, asking for one result gave
the best *bm25* row while asking for twenty gave the best *re-ranked* row, and
paging showed different articles than a single larger request. That is mildly
wrong across 57 articles and badly wrong across tens of thousands, where a
common word matches hundreds of thin extracts and a strong article sitting
just outside the window can never be promoted no matter how well sourced it is.
`test_top_hit_does_not_depend_on_how_many_results_were_asked_for` pins it.

---

## Retrieval for answering ≠ search

Browsing search uses `OR`: a partial match is still a useful result.

Retrieval for the AI assistant uses `AND`. With `OR`, a question about a topic
the encyclopaedia has never covered still matches any article sharing one
ordinary word, so the assistant would believe it had grounding when it had none.
Requiring every salient term is what makes "the encyclopaedia does not cover
this" an outcome that actually happens. See [AI_SAFETY.md](AI_SAFETY.md).

---

## Scaling the library

Hand-authoring four reading levels per subject produces good articles at roughly
a dozen a day. It does not reach thousands. The importer
(`pipeline/wikipedia.py`) exists because that is the only honest way to close
the gap: bring in text someone else has already written, under a licence that
permits it, and say so.

**What the importer refuses to do** is as important as what it does. It does not
paraphrase, summarise or simplify. Rewriting source text produces sentences no
source supports — the exact failure the validator, the epistemic labels and the
grounded assistant all exist to prevent, arriving through the back door.

So the two reading levels come from two different wikis rather than from one
text processed twice:

| Level | Source | Why it is legitimate |
|---|---|---|
| `adult` | English Wikipedia lead section | Written for a general adult reader |
| `teen` | Simple English Wikipedia lead section | Independently written for limited-English readers |

Where no Simple English article exists, the article ships with the adult level
only. The reading-level resolver already handles partial coverage, and the
quality score reflects the gap rather than hiding it.

**Imported articles are not kids-safe, and carry no children's reading band.**
Simple English Wikipedia is written for readers with limited English — adult
learners included — not for children specifically, so the simplified text lands
at `teen`, not `age9_12`. Kids Mode stays what it claims to be: a subset a
person has actually read. The harvest spans wars, battles, diseases and human
anatomy; marking it safe because it imported cleanly would be precisely the
unearned claim the epistemic labels, the validator and the grounded assistant
all exist to refuse. The validator enforces the pairing — a children's reading
band on a `kids_safe=false` article is an error — so the two decisions cannot
drift apart. A reviewer can promote an imported article after reading it; the
opposite default cannot be undone once a child has seen the page.

**Precedence.** The importer receives the set of slugs already present in the
authored pack and skips them, so imported text can never displace written text
on the same subject.

**Pack formats.** Authored packs keep one file per article, which diffs cleanly
in review. Imported packs keep `articles.jsonl.gz` and `sources.json.gz`,
because tens of thousands of loose files make a repository unusable.
`read_pack_articles()` and `read_pack_json()` accept either, and a pack may mix
both.

**Where the cost lands.** Measured on the shipped library of 13,703 articles
(57 authored, 13,646 imported), from an empty database:

| Step | Time |
|---|---|
| migrate | < 0.1 s |
| load (validate + insert both packs) | ~5 s |
| index (FTS5 rebuild + optimize) | ~11.8 s |
| score (8 components × 13,703) | ~1.3 s |
| check (7 integrity checks) | ~0.3 s |
| **`setup`, end to end** | **~18.6 s** |

Loading and scoring log progress, because a step that takes ten seconds with no
output is indistinguishable from a hang. This is a one-off cost on first run and
after a content update, not a per-request cost — reads stay fast because they
are indexed lookups against a single current revision. Search returns in
2–30 ms across the full library; the slowest path is a did-you-mean correction
for a word in no article at all (~70 ms), which only runs when there are no
results to show anyway.

**What scale silently rigs.** Importing thousands of articles changes no single
article, but it changes the statistics behind every ranking that was not
explicitly defended, because the imports are numerous and all arrive at once:

| Surface | What breaks by default | Defence |
|---|---|---|
| Home page daily pick | Imports outnumber authored work ~200:1, so the shop window is almost surely a two-sentence extract | `SHOWCASE_FLOOR`, with a fallback so a small library still has a home page |
| "Recently updated" | A pack load stamps every row with one timestamp, handing the section to the import | Same floor |
| Category browse | `total` returned the page size, so a category holding 2,000 articles advertised 60 and hid the rest | Real `COUNT`, `has_more`, and paging in the UI |
| Search ranking | Re-ranking a 20-row window cannot promote a strong article ranked 21st by raw relevance | Wider candidate pool (above) |
| Admin dashboard | Thousands of routine findings of one kind bury a handful of errors of another | Findings grouped by kind and severity |

None of these are import-specific rules; they are properties the app should
have had at any size. Scale is what made them visible.

## Extension points

| To add | Do this | Not this |
|---|---|---|
| A new article type | Add an entry to `taxonomy.json` | Migrate the schema |
| A new AI provider | Implement `AIProvider.complete()` | Touch the assistant |
| A React/Tauri shell | Consume the existing JSON API | Rewrite the backend |
| A new content pack | Drop a directory in `content/packs/` | Change the loader |
| Semantic search | Populate `embedding` / `embedding_chunk` | Replace FTS5 |
| A new fact check | Add a method to `FactChecker` | Change the schema |
