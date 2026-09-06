# Content guide

How to write an article that the validator will accept and a reader can trust.

```bash
python run.py validate core   # check without loading
python run.py load core       # validate and load
```

The validator refuses to load anything with an `error`. Warnings load but raise
an `issue` row for the editorial queue.

---

## File layout

```
content/packs/core/
  pack.json        key, version, title
  taxonomy.json    article types and categories
  sources.json     the evidence catalogue
  media.json       media with licence metadata
  synonyms.json    query expansion
  quizzes.json     optional
  paths.json       optional learning paths
  articles/*.json  one file per article
```

---

## An article

```jsonc
{
  "slug": "tyrannosaurus-rex",          // lowercase-kebab-case, required
  "title": "Tyrannosaurus rex",
  "type": "dinosaur",                    // must exist in taxonomy.json
  "categories": ["dinosaurs", "animals"],
  "primary_category": "dinosaurs",       // must be one of `categories`
  "aliases": [
    { "text": "T. rex", "kind": "abbreviation" },
    { "text": "T-rex",  "kind": "misspelling" }   // yes, index misspellings
  ],
  "pronunciation_ipa": "/tɪˌrænəˈsɔːrəs ˈrɛks/",
  "kids_safe": true,
  "summary": "One or two sentences.",

  "facts": [
    {
      "key": "length",
      "label": "Length",
      "value": "Up to about 12 metres",
      "value_num": 12.0,                 // enables comparison and sorting
      "unit": "m",
      "epistemic": "estimate",           // see below
      "confidence": 0.85,
      "comparable_key": "body_length",   // shared across articles
      "group": "Size",
      "cite": [1]                        // citation markers supporting this fact
    }
  ],

  "content": {
    "age6_8":  { "summary": "…", "body": "…" },
    "age9_12": { "summary": "…", "body": "…" },
    "teen":    { "summary": "…", "body": "…" },
    "adult":   { "summary": "…", "body": "…" }   // REQUIRED
  },

  "citations": [
    {
      "marker": 1,
      "source": "amnh",                  // uid from sources.json
      "claim": "Body length and the range of published mass estimates.",
      "supports": "supports"             // supports | partially | background | contradicts
    }
  ],

  "relations": [ { "to": "triceratops", "kind": "contrasts_with" } ],
  "timeline":  [ { "title": "…", "start": -68000000, "end": -66000000,
                   "precision": "million_years", "importance": 5,
                   "epistemic": "estimate" } ],
  "places":    [ { "name": "Hell Creek Formation", "kind": "fossil_site",
                   "lat": 47.5, "lon": -106.9, "country": "US" } ],
  "review":    { "last_reviewed": "2026-09-06" }
}
```

---

## Reading levels

**Each level is written for its audience. It is not the adult text shortened.**

| Level | Voice |
|---|---|
| `age6_8` | Short sentences, familiar words, concrete comparisons. "Teeth as long as a banana." |
| `age9_12` | Real scientific vocabulary, explained. Introduce *why* we know things. |
| `teen` | Mechanisms and evidence. Name the disagreements. |
| `adult` | Full treatment. Methodology, uncertainty, open questions. |

`adult` is mandatory — it is the canonical text everything else is derived from.

The validator enforces this:

- **error** if a children's level is byte-identical to another level
- **warning** if a children's level exceeds its mean-sentence-length ceiling
  (14 words for `age6_8`, 21 for `age9_12`, 28 for `teen`)

Accuracy is never traded for simplicity. The age 6–8 T. rex text says the
dinosaurs died out; it does not say a comet definitely caused it.

---

## Epistemic status

The single most important field in the format.

| Value | Use for | Rendered as |
|---|---|---|
| `fact` | Established, directly evidenced | (no badge) |
| `estimate` | Calculated or modelled, not measured | **Estimate** |
| `interpretation` | Inferred from evidence, not observed | **Interpretation** |
| `contested` | Experts genuinely disagree | **Debated** |
| `uncertain` | Evidence does not settle it | **Uncertain** |
| `opinion` | A judgement | **Opinion** |

Worked examples from the shipped pack:

- T. rex **length** → `estimate` (confidence 0.85). Measured from skeletons, but
  the largest individual is unknown.
- T. rex **weight** → `estimate` (confidence 0.6). You cannot weigh a fossil;
  different modelling methods disagree substantially.
- Moon **origin** → `interpretation`. The giant-impact hypothesis is
  well-supported but is an inference, and its parameters are unresolved.
- Oldest **stone tools** → `contested`. The 3.3 Ma Lomekwi date is disputed
  within the field.
- Earth **diameter** → `fact`.

> If you would have to write "probably", "most scientists think", or "current
> estimates suggest" in prose, the fact is not `fact`.

Anything marked `fact` must carry `cite`. The validator warns otherwise — either
cite it or downgrade it.

---

## Citations

A citation binds **one claim** to **one source**. The `claim` field is not
optional and is not decorative: it states what the source is being asked to
support, and it is shown to the reader under the source entry.

```jsonc
{ "marker": 1, "source": "amnh",
  "claim": "Body length, hip height and the range of published mass estimates." }
```

In the body, reference it as `[1]`. Facts reference it as `"cite": [1]`.

`supports` is honest about strength:

| Value | Meaning |
|---|---|
| `supports` | Directly establishes the claim |
| `partially` | Supports part of it |
| `background` | Context, not proof |
| `contradicts` | Deliberately cited as disagreeing |

Validation errors: a body citing an undefined marker, a fact citing an undefined
marker, a duplicate marker, a citation with no claim, an unknown source uid, or
a published article with no citations at all.

---

## Writing standards

**State how we know, not only what is known.** "Because behaviour does not
fossilise, claims about how T. rex hunted are interpretations drawn from
indirect evidence" is better than asserting a hunting style.

**Correct misconceptions explicitly where the evidence is clear.** The pyramids
article states what the Giza workers' settlement excavation actually found —
bakeries, meat rations, healed fractures, prepared tombs — and why that is
incompatible with slavery. The human evolution article says plainly that humans
did not evolve from chimpanzees.

**Name disagreements rather than picking a side.** "The relative contribution of
the Chicxulub impact and Deccan volcanism remains an active area of research."

**Do not imply an old article is wrong.** Review dates reflect how fast a
subject moves. Mathematics does not expire; population statistics do.

---

## Review cadence

Set per type in `taxonomy.json`:

| Type | Months | Why |
|---|---|---|
| `country`, `city` | 12 | Population and economic figures change yearly |
| `technology` | 12 | Capability claims go stale |
| `medical` | 12 | Outdated clinical guidance can cause harm |
| `dinosaur` | 24 | Size estimates shift with new specimens |
| `historical_event` | 60 | Established history changes slowly |
| `math_concept` | 96 | Proved mathematics does not expire |

---

## Quizzes

`quizzes.json`. Every question needs an `explanation` — the loader rejects one
without it — and should name the `article` (and ideally the `source`) that backs
the answer, so a quiz can never assert something the encyclopaedia does not.

Four question types are implemented:

```jsonc
// multiple_choice (the default) and true_false
{
  "prompt": "Which dinosaur had three horns on its face?",
  "explanation": "Triceratops had two long horns above its eyes and one on its nose.",
  "article": "triceratops",
  "options": [
    { "text": "Triceratops", "correct": true },
    { "text": "Tyrannosaurus rex" }
  ]
}

// ordering — the array order IS the answer; the UI shuffles it
{
  "kind": "ordering",
  "prompt": "Put these in order — the longest ago first.",
  "explanation": "The Earth formed first, then dinosaurs, then people.",
  "options": [
    { "text": "🌍 The Earth forms" },
    { "text": "🦕 Dinosaurs live on Earth" },
    { "text": "🧑 The first people appear" }
  ]
}

// matching — each item names its partner
{
  "kind": "matching",
  "prompt": "Match each world to what it is known for.",
  "explanation": "…",
  "options": [
    { "text": "Earth", "match": "About 71% covered in water" },
    { "text": "Mars",  "match": "The largest known volcano" }
  ]
}
```

For `ordering` and `matching` there is no single correct option — the answer is
the sequence or the pairing — so the loader flags every option correct and stores
the answer in `sort_order` / `match_key`. Do not add `"correct": true` to them.

Writing questions:

- Ages 6–8: one idea per question, three options, concrete comparisons.
- Explanations teach. "No — T. rex ate meat" is weaker than explaining that its
  thick conical teeth were built for crushing bone.
- Use questions to correct misconceptions directly: whether people lived
  alongside dinosaurs, who built the pyramids, whether humans came from
  chimpanzees.
- Ask about *evidence*, not just facts. "Why are T. rex weight estimates given
  as a range?" teaches more than "How heavy was T. rex?"

## Explorer Trails

`trails.json` defines badges and trails. A trail is an ordered list of stations;
each names a quiz, a badge and an article to read first.

```jsonc
{
  "badges": [
    { "key": "bone-hunter", "title": "Bone Hunter", "icon": "🦕",
      "description": "You can tell what fossils prove from what they suggest.",
      "criteria": "Finish Dinosaur Valley" }
  ],
  "trails": [{
    "key": "explorer-trail", "title": "The Explorer Trail", "icon": "🧭",
    "age_band": "age9_12",
    "stations": [
      { "key": "dinosaur-valley", "title": "Dinosaur Valley",
        "subtitle": "Evidence from deep time", "icon": "🦕", "palette": "amber",
        "quiz": "junior-dinosaurs", "badge": "bone-hunter",
        "article": "cretaceous-period" }
    ],
    "completion_badge": "master-explorer"
  }]
}
```

`criteria` is required on every badge: the UI shows it *before* the badge is
earned, so a child can see what they are working towards rather than being
surprised by an unexplained reward.

`palette` is a name (`teal`, `amber`, `rose`, `violet`, `green`, `blue`), not a
colour value, so the theme decides the actual shade in light and dark mode.

Stations unlock in order. Clearing one (half marks or better) opens the next and
awards its badge. Adding a station is a JSON edit — the board renders whatever
the data describes.

## Media

Only add media whose licence you have verified.

```jsonc
{
  "uid": "diagram-solar-system",
  "kind": "diagram",
  "title": "…",
  "creator": "…",
  "credit": "…",                  // required
  "license": "CC BY 4.0",         // required
  "license_url": "…",
  "source_url": "…",
  "provenance": "creative_commons",
  "redistributable": true,        // true requires local_path + sha256
  "local_path": "media/…",
  "sha256": "…"
}
```

`alt` text on every `article.media` entry is a hard error if missing.
Public access is not a licence to redistribute. See LICENSING.md.
