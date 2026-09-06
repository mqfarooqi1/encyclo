# Offline architecture

The application is offline-first in the strong sense: it has no online mode to
degrade from. Nothing is fetched at runtime, and outbound network access is
disabled by default (`ENCARTA_ALLOW_NETWORK=0`).

## What works with no network

Everything except the AI "Ask" tab: reading at all four levels, search,
autocomplete, spelling correction, knowledge graph, timeline, comparison,
quizzes, learning paths, bookmarks, notes, progress, the editorial dashboard.

Ask degrades honestly — it returns the retrieved articles and their cited
sources with no generated prose, rather than erroring or fabricating.

## How that is guaranteed

**No remote assets, enforced by CSP.**

```
default-src 'self'; script-src 'self'; img-src 'self' data: blob:;
font-src 'self'; connect-src 'self'; frame-ancestors 'none'
```

There are no web fonts, no CDN scripts, no analytics and no telemetry. Typography
uses system font stacks. Article covers are generated deterministically from the
slug in `dom.js` rather than being images — which also means no unverified
third-party media is shipped.

**No build step.** The frontend is ES modules served directly. There is no
bundler, no `node_modules`, and nothing to reinstall in three years.

**No third-party Python packages.** The base install is stdlib only. `waitress`
is optional for production serving; `ruff`, `mypy` and `pytest` are development
only.

**Personal data is local.** Bookmarks, notes and progress are in a separate
SQLite file that never leaves the machine and is never overwritten by a content
update.

## Content packs

A pack is a directory of JSON. Loading is idempotent and version-aware: an
unchanged article is a no-op, a changed one creates a new revision.

```
content/packs/<key>/
  pack.json  taxonomy.json  sources.json  media.json
  synonyms.json  quizzes.json  paths.json  articles/*.json
```

Installed packs are recorded in `content_pack` with `article_count` and version;
`pack_article` maps membership, so a pack can be identified and removed.

Planned editions — Core, Kids, Science, History, Geography, Space, Animals — are
a packaging concern, not an architectural one. The loader already handles
multiple packs; what is missing is a distribution format (a signed archive with
a manifest, resumable download and integrity check), not engine support.

## Offline AI

`ENCARTA_AI_PROVIDER=local` targets an Ollama-compatible server on the same
machine. It needs no API key and no internet, and `LocalProvider.available` is
unconditionally true because a local server is not a network dependency in the
sense that matters here.

If the local server is absent, the provider reports that plainly and the app
falls back to retrieved articles.

## Deployment

Development uses `wsgiref` with a threading server. For anything longer-lived,
the app is a plain WSGI callable:

```bash
python -m pip install waitress
python -c "from waitress import serve; import sys; sys.path.insert(0,'src'); \
           from encarta.web.api import create_app; serve(create_app(), port=8000)"
```

Binding to `127.0.0.1` by default is intentional. There is no authentication
layer, and the editorial dashboard is not access-controlled — exposing this to a
network requires putting a reverse proxy and auth in front of it first.
