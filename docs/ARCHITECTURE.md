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
article. The final score blends four signals:

```
score = -bm25(weighted columns)      # lexical relevance
      + 100  if title == query        # exact title wins outright
      +  40  if title startswith query
      +  15  if all terms in title
      + 3 × mean(5 - source_tier)     # better-sourced articles rank higher
      + quality_score / 20            # editorial completeness
```

Column weights are `title 12, aliases 9, summary 4, body 1, facts 2.5,
categories 2` — a title hit should beat a passing mention in a long body.

Ranking is deliberately **not** influenced by view counts. Popularity is not
evidence.

One subtlety worth stating: SQL orders by `bm25` alone, so the results must be
re-sorted in Python after the trust signals are folded in. Skipping that step
leaves the extra signals computed but inert — a bug this project shipped
briefly, and `test_results_are_ordered_by_final_score_not_raw_bm25` now prevents.

---

## Retrieval for answering ≠ search

Browsing search uses `OR`: a partial match is still a useful result.

Retrieval for the AI assistant uses `AND`. With `OR`, a question about a topic
the encyclopaedia has never covered still matches any article sharing one
ordinary word, so the assistant would believe it had grounding when it had none.
Requiring every salient term is what makes "the encyclopaedia does not cover
this" an outcome that actually happens. See [AI_SAFETY.md](AI_SAFETY.md).

---

## Extension points

| To add | Do this | Not this |
|---|---|---|
| A new article type | Add an entry to `taxonomy.json` | Migrate the schema |
| A new AI provider | Implement `AIProvider.complete()` | Touch the assistant |
| A React/Tauri shell | Consume the existing JSON API | Rewrite the backend |
| A new content pack | Drop a directory in `content/packs/` | Change the loader |
| Semantic search | Populate `embedding` / `embedding_chunk` | Replace FTS5 |
| A new fact check | Add a method to `FactChecker` | Change the schema |
