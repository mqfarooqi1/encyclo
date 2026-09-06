# AI safety

The rule this document exists to enforce:

> **The AI may only restate what the encyclopaedia and its cited sources already
> say. It may never add a fact, and it may never be the reason a reader believes
> something.**

Everything below is implemented and tested. `tests/test_ai_grounding.py` fails
if any of it stops being true.

---

## Default: no AI at all

`ENCARTA_AI_PROVIDER` defaults to `none`, which loads `NullProvider`. It does
not generate. It reports that generation is unavailable and returns the
retrieved articles instead.

This matters because it makes the degraded path the *normal* path. A system
where the safe fallback is rarely exercised is a system whose safe fallback does
not work.

**Never required for:** reading articles, search, quizzes, timeline, knowledge
graph, comparison, maps, bookmarks — that is, everything except the "Ask" tab.

---

## The answering pipeline

```
question
   │
   ▼
[1] retrieve — FTS5, require_all=True
   │
   ├── no passages ─────► REFUSE. The model is never called.
   │                      "The encyclopaedia does not have an article
   │                       covering this yet."
   ▼
[2] provider available?
   │
   ├── no ──────────────► DEGRADE. Return the real passages and their
   │                      cited sources, with no generated prose.
   ▼
[3] build prompt — passages only, plus each article's source list
   │
   ▼
[4] complete() with the grounding system prompt
   │
   ├── empty / unreachable ─► DEGRADE as above.
   ▼
[5] verify every [Pn] marker against the passages actually supplied
   │
   ▼
answer + passages + sources + disclaimer + invalid_citations
```

### Step 1 is the load-bearing one

Retrieval uses `AND` matching, not `OR`.

This is not a tuning detail. With `OR`, the query *"What is the capital of Zog
in the Fnord system?"* still matches every article containing the word "system",
and the assistant would be handed five irrelevant passages and told they are its
grounding. It would then produce something fluent and wrong, with citations
pointing at real articles that do not support the claim — the worst possible
failure mode, because it looks correct.

Requiring every salient term means "not covered" is a real outcome:

| Question | Grounded | Passages |
|---|---|---|
| Why did the dinosaurs die out? | yes | 4 |
| What is a black hole? | yes | 3 |
| How do plants make food? | yes | 1 |
| What is the capital of Zog in the Fnord system? | **no** | 0 |
| Tell me about quantum chromodynamics | **no** | 0 |

The last two are correct behaviour. The encyclopaedia does not cover them, and
says so.

---

## The system prompt

```
1. Answer ONLY using the numbered passages provided.
2. If the passages do not answer the question, say so plainly.
   Do not fill the gap from your own knowledge.
3. Cite passages inline as [P1], [P2].
4. NEVER invent a citation, a URL, a statistic, a date or a source title.
5. Carry uncertainty through: an estimate stays an estimate, a debated
   point stays debated. Do not upgrade a hypothesis into a settled fact.
6. Where passages disagree, say so rather than choosing a side.
7. Write for the stated reading level, without sacrificing accuracy.
```

Rule 5 is the one most easily lost. The encyclopaedia goes to considerable
trouble to mark T. rex's mass as an estimate with a range; an assistant that
flattens that into "T. rex weighed 8 tonnes" has undone the work.

---

## Citation verification

A prompt is a request, not a guarantee. Every `[Pn]` marker in the model's
output is checked against the passages actually supplied:

```python
used  = {int(m) for m in re.findall(r"\[P(\d{1,2})\]", text)}
valid = {p.number for p in passages}
invalid = used - valid
```

`invalid_citations` is returned to the client and **rendered as a warning to the
reader**, not silently dropped. A model citing a passage that does not exist is
the clearest available hallucination signal, and hiding it would waste it.

---

## What the AI cannot do

| Capability | Status | Enforced by |
|---|---|---|
| Write to any table | Never | No write path exists in `ai/` |
| Publish a revision | Never | `CHECK (origin <> 'ai_approved' OR reviewed_by IS NOT NULL)` |
| Be recorded as a source | Never | `source.source_type` has no AI value; see SOURCE_POLICY.md |
| Answer without retrieval | Never | Step 1 returns before the provider is constructed |
| Reach the network when disabled | Never | `HTTPProvider._guard()` checks `allow_network` first |
| Talk unsupervised to children | Never | Kids Mode forces a child reading level and hides the Ask tab |

An AI-authored revision is a *proposal*. It sits in `update_proposal` with
`status='pending'` and cannot leave that state without a named reviewer — a
database constraint, not a convention.

---

## Kids Mode

- Reading level is forced to `age6_8` or `age9_12`; `adult` is unreachable.
- Articles flagged `kids_safe = 0` return 403.
- Categories flagged `kids_safe = 0` are hidden from navigation.
- The Ask tab is removed from navigation entirely.
- The validator rejects any article that is `kids_safe: false` yet offers
  children's reading levels.

---

## Secret handling

- API keys are read from the environment on demand and never stored on the
  config object, so they cannot be serialised into a log line or an API response.
- `logging_setup.RedactingFilter` scrubs credential-shaped strings from all log
  output.
- Keys never reach the browser. All provider calls are server-side.
- `.env` is git-ignored; `.env.example` documents the variables with no values.

---

## Known limits

- **Prompt injection via article text** is not currently mitigated. All content
  is locally authored and validated, so the threat is low today, but a future
  pipeline ingesting third-party text would need passage sanitisation.
- **Retrieval recall** is lexical. `AND` matching trades recall for safety: a
  question phrased entirely in synonyms may be refused even though the
  encyclopaedia covers it. That is the correct direction to fail in, but a
  semantic layer (`embedding_chunk`) would reduce it.
- **The model can still be wrong within its grounding** — it may misread a
  passage. Citation verification catches invented references, not misreadings.
  This is why every answer carries a disclaimer and links to its passages.
