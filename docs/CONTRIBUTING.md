# Contributing

## Before anything

```bash
python run.py setup
python -m pytest -q && python -m ruff check src tests run.py && python -m mypy
```

All three must pass.

## Contributing an article

1. Read [CONTENT_GUIDE.md](CONTENT_GUIDE.md).
2. Write `content/packs/core/articles/<slug>.json`.
3. `python run.py validate core` — fix every error.
4. `python run.py load core && python run.py index && python run.py score`.
5. Read it in the browser at all four reading levels.

Checklist:

- [ ] All four reading levels, each genuinely written for its audience
- [ ] Every `epistemic: "fact"` entry has a `cite`
- [ ] Estimates are marked `estimate` with a `confidence`
- [ ] Contested claims are marked `contested` and the disagreement is described
- [ ] Every citation states the specific claim it supports
- [ ] Relations point at articles that exist
- [ ] Media has `alt` text
- [ ] The article says *how we know*, not only what is known

## Contributing code

- Keep repositories read-only; writes go through the loader or the pipeline.
- Add a test for anything that could regress silently. Prefer tests that assert
  a *property* ("no published article is uncited") over tests that assert a
  fixture.
- Never edit an applied migration; add a new one.
- Never assign a database string to `innerHTML`.
- If a feature cannot be finished, label it as unavailable in the UI rather than
  shipping a control that does nothing.

## Commit messages

Explain the reasoning, not the diff. A message that says *why* the change was
necessary is worth more than one that restates what changed.

## What will be declined

- Content whose sources cannot be verified
- Media without a licence
- Anything that lets AI output be published without human review
- Anything requiring a network connection for core reading
- Ranking by popularity
- Engagement mechanics: streaks, notifications, anything designed to extend
  screen time
