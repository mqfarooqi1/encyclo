# Database

SQLite, two files, seven migrations. Every table below exists because something
in the trust chain needs it.

```
SOURCE → EVIDENCE → ARTICLE → CITATION → VERSION → REVIEW
```

Run `python run.py migrate` to create or upgrade. Migrations are forward-only,
applied in numeric order inside a transaction, and recorded with a checksum.
**Editing an already-applied migration raises an error** rather than being
ignored — a history you can silently rewrite is worse than none.

---

## Files

| File | Contents | Lifecycle |
|---|---|---|
| `data/encarta-content.db` | Articles, revisions, sources, media, graph, index | Replaceable by a content pack |
| `data/encarta-user.db` | Bookmarks, notes, progress, quiz attempts | Never shipped, never overwritten |

Attached to one connection as `main` and `usr`. See ARCHITECTURE.md for the
`executescript` trap this arrangement contains.

---

## 0001_core — articles

| Table | Purpose |
|---|---|
| `article_type` | Extension point. New types (`dinosaur`, `planet`, `war`…) are data, not schema. Carries a JSON `fact_schema` and a default review cadence. |
| `category` | Hierarchical subject tree with a `kids_safe` flag. |
| `article` | Identity, status, and denormalised fields for fast listing. Points at `current_revision_id`. |
| `article_alias` | Alternative names — scientific, former, abbreviation, **misspelling**. Feeds search and URL resolution. |
| `article_category` | Many-to-many, with a partial unique index enforcing at most one primary category. |
| `article_revision` | **Append-only.** Version, parent, origin, author, reviewer, content hash. |
| `article_content` | One row per (revision, reading level). Four independently authored bodies. |
| `fact` | Structured quick-facts with `epistemic`, `confidence` and `comparable_key`. |

Two constraints carry real weight:

```sql
-- An AI-authored revision cannot be published without a named reviewer.
CHECK (origin <> 'ai_approved' OR reviewed_by IS NOT NULL)

-- At most one primary category per article.
CREATE UNIQUE INDEX idx_artcat_one_primary
  ON article_category(article_id) WHERE is_primary = 1;
```

`fact.epistemic` is the core trust primitive:
`fact | estimate | interpretation | opinion | uncertain | contested`.
Anything that is not `fact` is badged in the UI.

`fact.comparable_key` is what makes Comparison Mode possible: two articles using
`body_mass` can be compared even though their fact keys differ.

---

## 0002_sources — evidence

| Table | Purpose |
|---|---|
| `source` | Title, publisher, authors, URL/DOI/ISBN, dates, licence, `tier` (1–4), `verification_status`. |
| `citation` | Binds **one claim to one source**, scoped to a revision. Carries the claim text and how well the source supports it. |
| `fact_citation` | Many-to-many between facts and citations. |
| `media` | Licence, creator, credit line, provenance, `is_redistributable`, checksum. |
| `article_media` | Role (`hero`, `diagram`…), caption, and mandatory `alt_text`. |

Why `fact_citation` is a join table rather than a column: one source routinely
establishes several facts at once — a NASA planet page supplies diameter, mass
and orbital period together. Modelling it as `citation.fact_id` forces authors
to duplicate a citation per fact, which is exactly how citation lists become
dishonest. This project shipped the column version first; the many-to-many is
the correction.

Citations hang off a *revision*, so rolling an article back also rolls back
precisely the evidence that supported it.

```sql
-- Anything bundled offline must have a local file and a checksum.
CHECK (is_redistributable = 0 OR (local_path IS NOT NULL AND sha256 IS NOT NULL))
```

---

## 0003_graph — connections, time, place

| Table | Purpose |
|---|---|
| `relation` | Typed directed edges (`part_of`, `lived_during`, `discovered_by`, `causes`…) with weight. |
| `timeline_event` | Signed real years, so one axis spans −4.54e9 to today. Explicit `precision` and `epistemic`. |
| `place` | Point or GeoJSON geometry, country code, and optional validity years for historical borders. |
| `place_bbox` | R-Tree virtual table for viewport and proximity queries. |

Years as signed reals is what lets the timeline zoom continuously from the
formation of the Earth to 1969 without a second representation.

---

## 0004_learning — quizzes and paths

`quiz`, `quiz_question`, `quiz_option`, `learning_path`, `learning_path_step`.

`quiz_question.explanation` is `NOT NULL`, and `article_id` / `source_id` ground
the answer. A quiz can therefore never assert something the encyclopaedia does
not.

---

## 0005_pipeline — review and quality

| Table | Purpose |
|---|---|
| `review_policy` | Per-type or per-category review cadence. |
| `update_proposal` | An AI or importer suggestion. Inert until reviewed. |
| `proposal_source` | The evidence a proposal was derived from. |
| `issue` | Fact-check findings. **Flags, never auto-corrects.** |
| `quality_report` | Component breakdown behind `article.quality_score`. |
| `content_pack`, `pack_article` | Installed pack inventory. |
| `audit_log` | Append-only record of every content mutation. |

```sql
-- A proposal cannot leave 'pending' without a named reviewer.
CHECK (status = 'pending' OR status = 'superseded' OR reviewer IS NOT NULL)
```

---

## 0006_search

`article_fts` is an FTS5 table over `title, aliases, summary, body, facts,
categories`, with `unicode61 remove_diacritics 2` and `prefix='2 3 4'`.

It is **not** an external-content table and **not** trigger-maintained.
Indexable text spans article + current revision + every reading level + facts +
categories, so it is rebuilt explicitly by `SearchIndexer`. That keeps the index
aligned with the trust model: only *published current* revisions are searchable,
so an unreviewed edit can never become discoverable by accident.

`article_fts_vocab` (fts5vocab) supplies the term dictionary for did-you-mean —
no external spellcheck dictionary is shipped.

`synonym` handles query expansion. `embedding` / `embedding_chunk` are the
optional semantic layer; the app works fully with them empty.

---

## user/0001_userdata

`setting`, `bookmark`, `collection`, `collection_item`, `note`,
`reading_progress`, `quiz_attempt`, `path_progress`.

Referenced by `article_slug` rather than by id, so a content pack can be rebuilt
from scratch without orphaning a single bookmark.

---

## Connection settings

```sql
PRAGMA journal_mode = WAL;      -- reads stay fast while the pipeline writes
PRAGMA foreign_keys = ON;       -- OFF by default; every CASCADE is inert without it
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -16000;     -- ~16 MB
```

`foreign_keys = ON` is per-connection and easy to omit; without it every
`ON DELETE CASCADE` in this schema silently does nothing.
`test_foreign_keys_are_enforced` pins it.

---

## Performance

Indexed for the access patterns the app actually has: status+title listing,
category joins, revision lookup by article, citation by source, relations in
both directions, timeline by span and importance, review queue by due date.

FTS5 with BM25 is O(matching documents), not O(corpus). Nothing loads the corpus
into memory; article bodies are fetched one revision at a time. The design
target of 100,000+ articles is a question of index size, not of architecture.
