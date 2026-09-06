# Licensing

## This project

| Part | Licence |
|---|---|
| Code | Apache-2.0 (`LICENSE`) |
| Original article text | CC BY-SA 4.0 |
| Generated article covers | CC0 (deterministic gradients, no third-party input) |

Code and content are licensed separately on purpose. Apache-2.0 is permissive
and patent-safe for the engine; CC BY-SA 4.0 is the convention for encyclopaedic
text and keeps derived article text open. Mixing the two is standard practice —
the code does not become CC BY-SA by shipping alongside content, and the content
does not become Apache by living in the same repository.

## Imported Wikipedia text

The `wikipedia` content pack is imported reference text, not original writing,
and the project is explicit about that in three places: the pack description,
the article page itself (a banner marks any article not from the `core` pack),
and the per-article citation.

**What is imported.** Lead sections from English Wikipedia (adult reading level)
and Simple English Wikipedia (ages 9–12). No text is paraphrased, rewritten or
simplified by the importer — doing so would produce sentences no source
supports, which is precisely the failure this project exists to avoid.

**Licence.** Wikipedia text is CC BY-SA 4.0. This project's original article
text is also CC BY-SA 4.0, so the share-alike condition is satisfied by
construction.

**Attribution.** Every imported article carries a citation to a *permanent
revision link* of the form:

```
https://en.wikipedia.org/w/index.php?curid=<pageid>&oldid=<revid>
```

This is the accepted way to credit Wikipedia authors: the linked revision's
history names them. A link to the live article would not, because the article
will have changed.

**Tier.** Imported sources are recorded at **tier 3** — a reputable secondary
reference — never tier 1. An encyclopaedia is a tertiary source, and the source
policy applies to Wikipedia exactly as it applies to anything else. Where an
article needs a stronger claim, it needs a stronger source.

**Precedence.** Hand-written articles always win. The importer is given the set
of slugs already present in `core` and refuses to produce an article for any of
them, so imported text never overwrites authored text on the same subject.

**API terms.** The importer identifies itself by User-Agent, batches requests to
the documented limits, rate-limits itself, and backs off on error. It uses the
official MediaWiki API rather than scraping rendered pages.

## Content categories

Every content item falls into exactly one, and the schema records which.

| Category | Meaning | Redistributable |
|---|---|---|
| **Original** | Written for this project | Yes, CC BY-SA 4.0 |
| **Openly licensed** | Public domain, CC, or government open data, with terms met | Yes, per its licence |
| **Third-party** | Cited but not copied | **No** — referenced by URL only |
| **User-generated** | Notes, bookmarks, collections | Stays local; never uploaded |
| **AI-generated draft** | Model output pending review | Not published until reviewed |

## Media rules

`media.is_redistributable` is the switch, and the schema enforces the
consequence:

```sql
CHECK (is_redistributable = 0 OR (local_path IS NOT NULL AND sha256 IS NOT NULL))
```

Media that is not redistributable is referenced by URL and never bundled into an
offline pack.

Every media row must carry `credit_line`, `license` and `provenance`. There is
no default that lets an unlicensed image in quietly.

The core pack ships **no bitmap media**. Article covers are generated
client-side from the slug. This is a licensing decision, not a design
limitation: shipping images means verifying every licence first.

## Rules that are not negotiable

1. **Public access is not permission.** That an image is on the web says nothing
   about redistribution rights.
2. **Attribution requirements are followed exactly**, including for CC BY and
   government works that request specific wording.
3. **Terms of service and `robots.txt` are respected.** No scraping in violation
   of a site's terms, no ignoring rate limits.
4. **Citing is not copying.** Storing a source's title, publisher, date and URL
   is normal scholarly practice. Mirroring its text or media is not, absent an
   explicit licence.
5. **No Encarta content.** This project takes inspiration from the idea of a
   rich offline educational encyclopaedia. It contains no Microsoft content,
   code, imagery, interface or branding.

## Sources suitable for import

Subject to per-item licence checking:

- Wikimedia Commons and Wikidata (CC BY-SA / CC0, attribution required)
- NASA, USGS, NOAA and other US federal works (generally public domain)
- Government open data portals (varies — check each)
- Museum open-access collections (Met, Smithsonian and others publish CC0 sets)
- Open educational resources with explicit licences

Each importer must record `license`, `license_url`, `source_url`,
`accessed_date` and `provenance` per item. An importer that cannot determine a
licence must not import.

## Attribution

Article sources are credited in the article, with publisher, tier and the
specific claim supported. Media credit lines are shown with the media. The
footer carries the pack-level licence.
