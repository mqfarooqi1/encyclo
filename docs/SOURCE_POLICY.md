# Source policy

## Tiers

| Tier | Category | Examples in the core pack |
|---|---|---|
| **1** | Government agency, university, peer-reviewed publication, national museum, international scientific body | NASA, USGS, NOAA, Smithsonian, Natural History Museum London, AMNH, Field Museum, IUCN, NIH/NLM, NHGRI, WHO, CERN, Library of Congress, British Museum, UNESCO, IPCC, ABS |
| **2** | Major educational or professional institution | Internet Society, WWF |
| **3** | Reputable secondary reference | Encyclopaedia Britannica |
| **4** | General web | (none used) |

Tier feeds search ranking (`mean(5 - tier)`), the quality score's
`source_quality` component, and the badge shown beside each source.

## AI output is never a source

Not at tier 4, not at any tier. `source.source_type` has no value for it.
A model can help draft, and that draft records `origin='ai_proposal'` on the
revision — but the *evidence* must be an external, citable source.

## Verification is earned

Every source starts `verification_status = 'unverified'`. It is promoted only by
the link checker, which requires `ENCARTA_ALLOW_NETWORK=1`.

The UI shows **"Link unverified"** beside such sources. This is deliberate and
correct: writing a URL down does not make it live, and claiming otherwise would
be exactly the kind of unearned confidence this project exists to avoid.

States: `unverified → verified | broken | moved | paywalled`. `broken` and
`moved` raise an `issue` for the editorial queue.

## Choosing sources

**Prefer** the institution that produced the data over one reporting it. For
planetary measurements, NASA rather than a news article about NASA.

**Prefer** a source that states its own uncertainty. A page giving a mass range
is more useful than one giving a single confident number.

**Do not** use a tier 3 source as the sole support for a numeric claim.
Britannica is used in this pack for orientation, never alone for a figure.

**Do** cite a source that disagrees, using `"supports": "contradicts"`, when the
disagreement is the point.

## Sources are per revision

`citation.revision_id` means rolling an article back restores exactly the
evidence that supported that version — not today's evidence attached to
yesterday's text.

## Licensing

Citing a source is not redistributing it. This project stores bibliographic
metadata and a URL, which is normal scholarly practice. It does not copy source
text beyond short attributed quotes, and it does not mirror source media unless
the licence explicitly permits it. See LICENSING.md.
