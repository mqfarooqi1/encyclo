# Development

## Setup

Requires Python 3.11+. No other runtime.

```bash
python run.py setup
python run.py serve
```

Development tooling is optional:

```bash
python -m pip install --user pytest ruff mypy
```

## Quality gate

All three must pass before a change is considered done.

```bash
python -m pytest -q
python -m ruff check src tests run.py
python -m mypy
```

Current state: 100 tests, ruff clean, mypy clean across 31 source files.

## Layout

```
src/encarta/
  config.py          env + .env, secrets read on demand only
  logging_setup.py   rotating logs with credential redaction
  db/                connection pool, migrations, *.sql
  domain/            enums and dataclasses — the shared vocabulary
  content/           validate.py (the editorial gate), loader.py (the only write path)
  repositories/      reads only, current published revisions only
  services/          search (index + query), quality (scoring + fact checking)
  ai/                provider abstraction, grounded assistant
  pipeline/          update and review machinery
  web/               WSGI app, API, static frontend
content/packs/core/  the seed content
tests/               100 tests
```

## Conventions

- **Repositories never write.** Every write goes through the loader or the
  pipeline, so there is one auditable path by which content changes.
- **Never read a non-current revision in reader-facing code.** Drafts are
  invisible by construction.
- **SQL fragments interpolated into f-strings must be literals from this
  codebase.** All values are bound parameters. Where a fragment is interpolated
  (`kids_only` clauses, schema names), it comes from a fixed allowlist.
- **The frontend never assigns a database string to `innerHTML`.** Build nodes
  with `el()`. The Markdown renderer produces DOM nodes, not HTML strings.
- **Every capability the UI offers must work, or be labelled unavailable.**
  Disabled reading levels are visibly disabled and explain why; unverified
  sources say so; a missing AI provider is stated rather than hidden.

## Adding things

**An article** — write `content/packs/core/articles/<slug>.json`, then
`python run.py validate core` and `python run.py load core`. See CONTENT_GUIDE.md.

**An article type or category** — add to `taxonomy.json`. No migration.

**A schema change** — add a new `NNNN_name.sql`. Never edit an applied
migration; the checksum guard will reject it.

**An API endpoint** — add to `create_router` in `web/api.py`, then a test in
`tests/test_api.py`.

**An AI provider** — subclass `HTTPProvider`, implement `complete()`, register
in `_PROVIDERS`. Nothing else changes.

**A fact check** — add a method to `FactChecker` and list it in `run()`.
It must raise an `issue`, never modify content.

## Testing notes

`conftest.py` builds a real database from the real content pack once per
session, so the suite exercises the shipped migrations, validator and loader
rather than fixtures that can drift from production.

Some tests assert properties of the *content*, not just the code —
`test_every_published_article_cites_at_least_one_source`,
`test_facts_marked_as_established_are_cited`,
`test_shipped_core_pack_has_no_validation_errors`. These fail if an author
breaks an editorial rule, which is the point.

`test_search.py` includes a parametrised hostile-input case: FTS5 has its own
query syntax and raw user input must never reach it as syntax.

## Debugging

```bash
python run.py --log-level DEBUG serve
python run.py stats
python run.py check          # what the fact checker currently sees
```

Logs go to stderr and `data/encarta.log`, with credential-shaped strings redacted.

## Known rough edges

- The dev server is `wsgiref`. Fine for local use; use waitress for anything else.
- The editorial dashboard has no access control. Do not expose the app to a
  network without putting auth in front of it.
- Search is lexical only. The `embedding` tables exist but are unpopulated.
- `on_this_day` falls back to notable anniversaries when no event matches today's
  date, since the seed set is small.
