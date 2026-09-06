/* View renderers. Each returns a DOM node for the router to mount. */

import { api, state, setLevel, formatYear, levelLabel, ApiError } from './api.js';
import { el, frag, coverFor, gradientFor } from './dom.js';
import { renderMarkdown, renderSnippet, excerpt } from './markdown.js';

const LEVELS = ['age6_8', 'age9_12', 'teen', 'adult'];
const KID_LEVELS = ['age6_8', 'age9_12'];

const go = (hash) => { window.location.hash = hash; };

function wrap(...children) { return el('div', { class: 'wrap' }, ...children); }

export function spinner() { return el('div', { class: 'spinner', role: 'status', 'aria-label': 'Loading' }); }

export function errorView(error) {
  const notFound = error instanceof ApiError && error.status === 404;
  return wrap(el('div', { class: 'empty', style: { marginTop: '48px' } },
    el('h2', {}, notFound ? 'Not in the encyclopaedia yet' : 'Something went wrong'),
    el('p', {}, error.message || String(error)),
    el('p', { style: { marginTop: '18px' } },
      el('a', { class: 'btn ghost', href: '#/', 'data-link': '' }, 'Back to the home page')),
  ));
}

function articleCard(item) {
  return el('a', { class: 'card', href: `#/article/${item.slug}`, 'data-link': '' },
    coverFor(item.slug, item.icon || '📄'),
    el('div', { class: 'card-body' },
      el('h3', {}, item.title),
      el('p', { class: 'desc' }, excerpt(item.summary, 150)),
      el('div', { class: 'meta' },
        item.category && el('span', {}, item.category),
        item.quality_score != null && el('span', { class: 'badge', title: 'Editorial quality score' },
          `${item.quality_score}/100`),
      ),
    ),
  );
}

function epistemicBadge(fact) {
  if (!fact.needs_qualifier) return null;
  const tone = { estimate: 'amber', uncertain: 'amber', contested: 'rose',
    interpretation: 'violet', opinion: 'violet' }[fact.epistemic] || '';
  const title = {
    estimate: 'A calculated estimate, not a direct measurement',
    interpretation: 'An interpretation drawn from evidence, not a direct observation',
    contested: 'Experts genuinely disagree about this',
    uncertain: 'The evidence does not settle this',
    opinion: 'A judgement rather than a finding',
  }[fact.epistemic] || fact.epistemic_label;
  return el('span', { class: `badge ${tone}`, title }, fact.epistemic_label);
}

/* ------------------------------------------------------------------ home -- */
export async function homeView() {
  const data = await api.home();
  const root = el('div');

  root.append(el('section', { class: 'hero' }, wrap(
    el('h1', {}, state.kids ? 'What shall we find out today?' : 'What would you like to explore?'),
    el('p', { class: 'lede' }, state.kids
      ? 'Pick something that looks interesting. Every answer here comes from a real museum, university or space agency.'
      : 'An encyclopaedia built around evidence: every article names its sources, records what is an estimate rather than a fact, and keeps its full revision history.'),
    el('form', {
      class: 'hero-search',
      onsubmit: (event) => {
        event.preventDefault();
        const value = event.target.elements.hq.value.trim();
        if (value) go(`#/search/${encodeURIComponent(value)}`);
      },
    }, el('input', {
      name: 'hq', type: 'search', placeholder: 'Try “largest dinosaur” or “why is Mars red”',
      'aria-label': 'Search the encyclopaedia',
    })),
    el('div', { class: 'stat-row', style: { marginTop: '26px' } },
      stat(data.stats.articles, 'Articles'),
      stat(data.stats.sources, 'Sources'),
      stat(data.stats.relations, 'Connections'),
      stat(data.stats.events, 'Timeline events'),
      data.stats.avg_quality != null && stat(data.stats.avg_quality, 'Avg quality'),
    ),
  )));

  if (data.discovery) {
    root.append(el('section', { class: 'band' }, wrap(
      el('div', { class: 'eyebrow' }, "Today's discovery"),
      el('a', { class: 'feature', href: `#/article/${data.discovery.slug}`, 'data-link': '',
        style: { textDecoration: 'none', color: 'inherit' } },
        el('div', { class: 'feature-art', style: { background: gradientFor(data.discovery.slug) },
          'aria-hidden': 'true' }),
        el('div', { class: 'feature-text' },
          el('div', { class: 'eyebrow' }, data.discovery.category || data.discovery.type_label),
          el('h2', {}, data.discovery.title),
          el('p', {}, excerpt(data.discovery.summary, 260)),
          el('span', { class: 'btn ghost', style: { alignSelf: 'flex-start', marginTop: '10px' } },
            'Read the article'),
        ),
      ),
    )));
  }

  if (data.did_you_know?.length) {
    root.append(el('section', { class: 'band' }, wrap(
      el('div', { class: 'band-head' }, el('h2', {}, 'Did you know?')),
      el('div', { class: 'grid cols-3' }, data.did_you_know.map((f) =>
        el('a', { class: 'card', href: `#/article/${f.slug}`, 'data-link': '' },
          el('div', { class: 'card-body' },
            el('div', { class: 'eyebrow' }, f.label),
            el('h3', { style: { fontSize: '18px' } }, f.value_text + (f.unit ? ` ${f.unit}` : '')),
            el('div', { class: 'meta' },
              el('span', {}, f.title),
              f.epistemic !== 'fact' && el('span', { class: 'badge amber' }, 'Estimate'),
            ),
          ),
        ))),
    )));
  }

  root.append(el('section', { class: 'band' }, wrap(
    el('div', { class: 'band-head' },
      el('h2', {}, 'Explore by subject'),
      el('a', { href: '#/random', 'data-link': '', class: 'chip-btn' }, '🎲 Surprise me'),
    ),
    el('div', { class: 'grid cols-3' }, data.categories
      .filter((c) => c.article_count > 0)
      .map((c) => el('a', { class: 'cat-card', href: `#/category/${c.key}`, 'data-link': '' },
        el('span', { class: 'ico', 'aria-hidden': 'true' }, c.icon || '📚'),
        el('span', {}, el('strong', {}, c.label),
          el('span', {}, `${c.article_count} article${c.article_count === 1 ? '' : 's'}`)),
      ))),
  )));

  if (data.learning_paths?.length) {
    root.append(el('section', { class: 'band' }, wrap(
      el('div', { class: 'band-head' },
        el('h2', {}, 'Learning paths'),
        el('span', { class: 'sub' }, 'Guided routes through connected topics')),
      el('div', { class: 'grid cols-3' }, data.learning_paths.map((p) =>
        el('a', { class: 'card', href: `#/path/${p.key}`, 'data-link': '' },
          el('div', { class: 'card-body' },
            el('div', { style: { fontSize: '28px' } }, p.icon || '🧭'),
            el('h3', {}, p.title),
            el('p', { class: 'desc' }, p.description),
            el('div', { class: 'meta' },
              el('span', { class: 'badge accent' }, `${p.steps} steps`),
              el('span', {}, levelLabel(p.age_band))),
          ),
        ))),
    )));
  }

  if (data.featured?.length) {
    root.append(el('section', { class: 'band' }, wrap(
      el('div', { class: 'band-head' },
        el('h2', {}, 'Best-evidenced articles'),
        el('span', { class: 'sub' }, 'Ranked by source quality, not by popularity')),
      el('div', { class: 'grid cols-4' }, data.featured.map(articleCard)),
    )));
  }

  if (data.on_this_day?.length) {
    root.append(el('section', { class: 'band' }, wrap(
      el('div', { class: 'band-head' }, el('h2', {}, 'Moments worth knowing')),
      el('div', { class: 'timeline' }, data.on_this_day.map((e) =>
        el('div', { class: 'tl-item' },
          el('div', { class: 'tl-era' }, formatYear(e.start_year)),
          el('h3', {}, e.slug
            ? el('a', { href: `#/article/${e.slug}`, 'data-link': '',
                style: { color: 'inherit', textDecoration: 'none' } }, e.title)
            : e.title),
          e.description && el('p', {}, e.description),
        ))),
    )));
  }

  return root;
}

function stat(value, label) {
  return el('div', { class: 'stat' }, el('b', {}, value ?? '—'), el('span', {}, label));
}

/* ---------------------------------------------------------------- search -- */
export async function searchView(query) {
  const data = await api.search(query, { limit: 30 });
  const root = wrap(el('div', { style: { padding: '30px 0 60px' } }));
  const body = root.firstChild;

  body.append(el('h1', { style: { fontSize: '28px', marginBottom: '6px' } },
    `Results for “${data.query}”`));
  body.append(el('p', { style: { color: 'var(--ink-3)', fontSize: '13.5px' } },
    `${data.total} result${data.total === 1 ? '' : 's'} · ${data.took_ms} ms`));

  if (data.corrected_query) {
    body.append(el('div', { class: 'notice' },
      'Showing results for ',
      el('strong', {}, data.corrected_query),
      ' — nothing matched your original spelling.'));
  }

  if (!data.hits.length) {
    body.append(el('div', { class: 'empty', style: { marginTop: '24px' } },
      el('h2', {}, 'No articles match that yet'),
      el('p', {}, 'This encyclopaedia is deliberately small and fully sourced rather than large and thin. '
        + 'The topic may simply not be written yet.'),
      el('p', { style: { marginTop: '16px' } },
        el('a', { class: 'btn ghost', href: '#/categories', 'data-link': '' }, 'Browse everything')),
    ));
    return root;
  }

  for (const hit of data.hits) {
    body.append(el('a', { class: 'result', href: `#/article/${hit.slug}`, 'data-link': '' },
      el('div', { class: 'result-art', 'aria-hidden': 'true',
        style: { background: gradientFor(hit.slug) } }, hit.icon || ''),
      el('div', {},
        el('div', { class: 'result-title' }, hit.title),
        hit.snippet ? renderSnippet(hit.snippet)
          : el('div', { class: 'result-desc' }, excerpt(hit.summary, 190)),
        el('div', { class: 'result-meta' },
          el('span', { class: 'badge' }, hit.type),
          hit.category && el('span', {}, hit.category),
          hit.quality_score != null && el('span', { class: 'badge accent' }, `Quality ${hit.quality_score}`),
          hit.levels?.length && el('span', {}, `${hit.levels.length} reading levels`),
        ),
      ),
    ));
  }
  return root;
}

/* --------------------------------------------------------------- article -- */
export async function articleView(slug) {
  const wanted = state.kids && !KID_LEVELS.includes(state.level) ? 'age9_12' : state.level;
  const data = await api.article(slug, wanted);
  const root = el('div');

  const primary = data.categories.find((c) => c.is_primary) || data.categories[0];

  /* hero */
  root.append(el('header', { class: 'article-hero' },
    el('div', { class: 'art', 'aria-hidden': 'true', style: { background: gradientFor(data.slug) } }),
    el('div', { class: 'inner' }, wrap(
      el('div', { class: 'crumbs' },
        el('a', { href: '#/', 'data-link': '' }, 'Home'),
        el('span', { 'aria-hidden': 'true' }, '›'),
        primary && el('a', { href: `#/category/${primary.key}`, 'data-link': '' },
          `${primary.icon || ''} ${primary.label}`),
        el('span', { 'aria-hidden': 'true' }, '›'),
        el('span', {}, data.type.label),
      ),
      el('h1', {}, data.title),
      data.pronunciation_ipa && el('div', { class: 'ipa' }, data.pronunciation_ipa),
      el('p', { class: 'summary' }, data.summary),
    )),
  ));

  /* body + rail */
  const main = el('div', {});
  const rail = el('aside', { class: 'rail' });
  root.append(wrap(el('div', { class: 'article-layout' }, main, rail)));

  /* reading levels */
  const available = new Set(data.available_levels);
  const offered = state.kids ? LEVELS.filter((l) => KID_LEVELS.includes(l)) : LEVELS;
  main.append(el('div', { class: 'levels', role: 'group', 'aria-label': 'Reading level' },
    offered.map((lv) => el('button', {
      type: 'button',
      'aria-pressed': String(data.reading_level === lv),
      disabled: !available.has(lv),
      title: available.has(lv) ? `Read at ${levelLabel(lv)}` : 'Not written at this level yet',
      onclick: () => { setLevel(lv); go(`#/article/${slug}`); rerender(); },
    }, levelLabel(lv)))));

  if (data.level_substituted) {
    main.append(el('div', { class: 'notice' },
      `This article is not written at ${levelLabel(data.requested_level)} yet, `
      + `so you are reading the ${levelLabel(data.reading_level)} version.`));
  }

  /* prose */
  const scrollToSource = (n) => {
    const target = document.getElementById(`source-${n}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      target.animate?.([{ background: 'var(--accent-soft)' }, { background: 'transparent' }],
        { duration: 1400 });
    }
  };

  if (data.content) {
    main.append(el('article', { class: 'prose' },
      renderMarkdown(data.content.body_md, { onCite: scrollToSource })));
  } else {
    main.append(el('div', { class: 'empty' }, el('h2', {}, 'No text at this reading level yet')));
  }

  /* sources */
  if (data.citations.length) {
    main.append(el('section', { class: 'sources' },
      el('h2', { style: { fontSize: '21px', marginBottom: '4px' } }, 'Sources'),
      el('p', { style: { fontSize: '13px', color: 'var(--ink-3)', marginBottom: '14px' } },
        'Each entry states exactly which claim it supports.'),
      data.citations.map((c) => el('div', { class: 'source-item', id: `source-${c.marker}` },
        el('div', { class: 'source-num' }, String(c.marker)),
        el('div', {},
          el('div', { class: 'source-title' },
            c.url ? el('a', { href: c.url, target: '_blank', rel: 'noopener noreferrer' }, c.source_title)
              : c.source_title),
          el('div', { class: 'source-meta' },
            el('span', {}, c.publisher),
            el('span', { class: `badge ${c.tier === 1 ? 'accent' : ''} tier`,
              title: tierTitle(c.tier) }, `Tier ${c.tier}`),
            c.verification_status !== 'verified' && el('span', {
              class: 'badge amber',
              title: 'The link checker has not confirmed this URL yet. It requires network access.',
            }, 'Link unverified'),
            c.supports !== 'supports' && el('span', { class: 'badge violet' },
              c.supports === 'partially' ? 'Partial support' : c.supports),
          ),
          el('div', { class: 'source-claim' }, c.claim),
        ),
      )),
    ));
  }

  /* --- rail --- */
  if (data.facts.length) {
    const box = el('div', { class: 'factbox' }, el('header', {}, 'Quick facts'));
    const groups = new Map();
    for (const fact of data.facts) {
      const key = fact.group_label || '';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(fact);
    }
    for (const [group, facts] of groups) {
      const section = el('div', { class: 'fact-group' });
      if (group) section.append(el('h4', {}, group));
      const dl = el('dl', { style: { margin: '0' } });
      for (const fact of facts) {
        dl.append(el('div', { class: 'fact' },
          el('dt', {}, fact.label),
          el('dd', {},
            fact.value_text,
            epistemicBadge(fact),
            ...(fact.citations || []).map((n) => el('a', {
              class: 'cite', href: `#source-${n}`,
              onclick: (e) => { e.preventDefault(); scrollToSource(n); },
            }, String(n))),
          ),
        ));
      }
      section.append(dl);
      box.append(section);
    }
    rail.append(box);
  }

  rail.append(actionsPanel(data));

  if (data.related.length) {
    rail.append(el('div', { class: 'panel' },
      el('header', {}, 'Connected topics'),
      el('div', { class: 'rel-list' }, data.related.slice(0, 9).map((r) =>
        el('a', { class: 'rel-item', href: `#/article/${r.slug}`, 'data-link': '' },
          el('span', { 'aria-hidden': 'true' }, r.icon || '·'),
          el('span', {}, r.title),
          el('span', { class: 'rel-kind' }, r.label),
        ))),
      el('div', { class: 'body' },
        el('a', { class: 'btn ghost', href: `#/explore/${data.slug}`, 'data-link': '',
          style: { width: '100%', justifyContent: 'center' } }, 'Explore connections')),
    ));
  }

  if (data.timeline?.length) {
    rail.append(el('div', { class: 'panel' },
      el('header', {}, 'Timeline'),
      el('div', { class: 'body' }, el('div', { class: 'timeline' }, data.timeline.map((e) =>
        el('div', { class: 'tl-item', style: { paddingBottom: '16px' } },
          el('div', { class: 'tl-era' }, formatYear(e.start_year)),
          el('h3', { style: { fontSize: '15px' } }, e.title),
          e.epistemic !== 'fact' && el('span', { class: 'badge amber' }, 'Estimate'),
        )))),
    ));
  }

  if (data.quiz) {
    rail.append(el('div', { class: 'panel' },
      el('header', {}, 'Test yourself'),
      el('div', { class: 'body' },
        el('p', { style: { fontSize: '14px', marginBottom: '12px' } },
          `${data.quiz.title} — ${data.quiz.question_count} questions.`),
        el('a', { class: 'btn', href: `#/quiz/${data.quiz.key}`, 'data-link': '',
          style: { width: '100%', justifyContent: 'center' } }, 'Start the quiz')),
    ));
  }

  rail.append(provenancePanel(data));
  return root;
}

function tierTitle(tier) {
  return {
    1: 'Tier 1 — government agency, university, peer-reviewed publication or national museum',
    2: 'Tier 2 — major educational or professional institution',
    3: 'Tier 3 — reputable secondary reference',
    4: 'Tier 4 — general website',
  }[tier] || '';
}

function actionsPanel(data) {
  const button = el('button', { class: 'btn ghost', style: { width: '100%', justifyContent: 'center' } },
    '☆ Save this article');
  let saved = false;
  const refresh = () => {
    button.textContent = saved ? '★ Saved' : '☆ Save this article';
  };
  api.bookmarks().then((rows) => {
    saved = rows.some((r) => r.article_slug === data.slug);
    refresh();
  }).catch(() => { /* personalisation is optional; never block the article */ });
  button.addEventListener('click', async () => {
    try {
      if (saved) await api.removeBookmark(data.slug);
      else await api.addBookmark(data.slug);
      saved = !saved;
      refresh();
    } catch { button.textContent = 'Could not save'; }
  });
  return el('div', { class: 'panel' }, el('div', { class: 'body',
    style: { display: 'flex', flexDirection: 'column', gap: '8px' } },
    button,
    el('a', { class: 'btn ghost', href: `#/ask/${encodeURIComponent(data.title)}`, 'data-link': '',
      style: { width: '100%', justifyContent: 'center' } }, '💬 Ask about this'),
  ));
}

function provenancePanel(data) {
  const score = data.quality_score;
  return el('div', { class: 'panel' },
    el('header', {}, 'Provenance'),
    el('div', { class: 'body', style: { fontSize: '13px', color: 'var(--ink-2)' } },
      score != null && el('div', { class: 'qbar', style: { marginBottom: '12px' } },
        el('span', { class: 'qnum' }, `${score}`),
        el('span', { class: 'qmeter' }, el('i', { style: { width: `${score}%` } })),
      ),
      el('div', {}, 'Version ', el('strong', {}, data.version || '—')),
      data.provenance?.origin && el('div', {}, 'Origin: ', el('strong', {}, data.provenance.origin)),
      data.last_reviewed_at && el('div', {}, 'Last reviewed: ', el('strong', {}, data.last_reviewed_at)),
      data.next_review_at && el('div', {}, 'Next review: ', el('strong', {}, data.next_review_at)),
      el('p', { style: { marginTop: '10px', fontSize: '12px', color: 'var(--ink-3)' } },
        'An older article is not a wrong one. Review dates reflect how quickly a subject changes.'),
      el('a', { href: `#/history/${data.slug}`, 'data-link': '', style: { fontSize: '13px' } },
        'Full revision history →'),
    ),
  );
}

/* --------------------------------------------------------------- history -- */
export async function historyView(slug) {
  const rows = await api.versions(slug);
  return wrap(el('div', { style: { padding: '30px 0 60px', maxWidth: '760px' } },
    el('div', { class: 'crumbs', style: { marginBottom: '10px' } },
      el('a', { href: `#/article/${slug}`, 'data-link': '' }, '← Back to the article')),
    el('h1', { style: { fontSize: '30px', marginBottom: '8px' } }, 'Revision history'),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '24px' } },
      'Revisions are append-only. Nothing is ever edited in place, so every version of '
      + 'this article — and the evidence that supported it — remains recoverable.'),
    el('div', { class: 'timeline' }, rows.map((r) => el('div', { class: 'tl-item' },
      el('div', { class: 'tl-era' }, `Version ${r.version}`, r.is_current ? ' · current' : ''),
      el('h3', {}, r.change_reason || 'Revision'),
      el('p', {}, `${r.created_at} · by ${r.created_by} · origin: ${r.origin}`),
      r.ai_model && el('p', {}, el('span', { class: 'badge violet' }, `AI: ${r.ai_model}`)),
      r.reviewed_by && el('p', {}, el('span', { class: 'badge accent' }, `Reviewed by ${r.reviewed_by}`)),
    ))),
  ));
}

/* -------------------------------------------------------------- category -- */
export async function categoryView(key) {
  const data = await api.category(key);
  return wrap(el('div', { style: { padding: '34px 0 60px' } },
    el('div', { style: { fontSize: '40px' } }, data.category.icon || '📚'),
    el('h1', { style: { fontSize: '36px', margin: '6px 0 8px' } }, data.category.label),
    data.category.description && el('p', {
      style: { color: 'var(--ink-2)', maxWidth: '60ch', marginBottom: '26px' } },
      data.category.description),
    data.articles.length
      ? el('div', { class: 'grid cols-4' }, data.articles.map((a) => articleCard(
        { ...a, icon: data.category.icon })))
      : el('div', { class: 'empty' }, el('h2', {}, 'No articles here yet')),
  ));
}

export async function categoriesView() {
  const rows = await api.categories();
  return wrap(el('div', { style: { padding: '34px 0 60px' } },
    el('h1', { style: { fontSize: '34px', marginBottom: '20px' } }, 'Browse everything'),
    el('div', { class: 'grid cols-3' }, rows.map((c) =>
      el('a', { class: 'cat-card', href: `#/category/${c.key}`, 'data-link': '' },
        el('span', { class: 'ico', 'aria-hidden': 'true' }, c.icon || '📚'),
        el('span', {}, el('strong', {}, c.label),
          el('span', {}, `${c.article_count} article${c.article_count === 1 ? '' : 's'}`)),
      ))),
  ));
}

/* -------------------------------------------------------------- timeline -- */
export async function timelineView() {
  const root = wrap(el('div', { style: { padding: '34px 0 60px' } }));
  const body = root.firstChild;
  body.append(el('h1', { style: { fontSize: '34px', marginBottom: '6px' } }, 'Timeline of everything'));
  body.append(el('p', { style: { color: 'var(--ink-2)', marginBottom: '20px' } },
    'From the formation of the Earth to the present day. Dates before the last few thousand '
    + 'years are estimates, and are marked as such.'));

  const RANGES = [
    ['All time', null, null],
    ['Deep time', -5e9, -1e6],
    ['Prehistory', -1e7, -3000],
    ['Ancient world', -4000, 500],
    ['Modern era', 1500, 2100],
  ];
  const list = el('div', { class: 'timeline' });
  const controls = el('div', { class: 'tl-controls' });

  const load = async (start, end, button) => {
    for (const other of controls.children) other.setAttribute('aria-pressed', 'false');
    button?.setAttribute('aria-pressed', 'true');
    list.replaceChildren(spinner());
    const rows = await api.timeline({ start, end, limit: 400 });
    list.replaceChildren(...(rows.length ? rows.map((e) => el('div', { class: 'tl-item' },
      el('div', { class: 'tl-era' }, formatYear(e.start_year),
        e.end_year && e.end_year !== e.start_year ? ` – ${formatYear(e.end_year)}` : ''),
      el('h3', {}, e.slug
        ? el('a', { href: `#/article/${e.slug}`, 'data-link': '',
            style: { color: 'inherit', textDecoration: 'none' } }, e.title)
        : e.title),
      e.description && el('p', {}, e.description),
      e.epistemic !== 'fact' && el('span', { class: 'badge amber', style: { marginTop: '5px' } },
        e.epistemic === 'estimate' ? 'Estimated date' : e.epistemic),
    )) : [el('div', { class: 'empty' }, el('h2', {}, 'No events in this range'))]));
  };

  for (const [label, start, end] of RANGES) {
    const button = el('button', { class: 'chip-btn', 'aria-pressed': 'false',
      onclick: () => load(start, end, button) }, label);
    controls.append(button);
  }
  body.append(controls, list);
  load(null, null, controls.firstChild);
  return root;
}

/* --------------------------------------------------------------- explore -- */
export async function exploreView(slug) {
  const data = await api.graph(slug, 2);
  const root = wrap(el('div', { style: { padding: '30px 0 60px' } }));
  const body = root.firstChild;

  body.append(el('div', { class: 'crumbs', style: { marginBottom: '10px' } },
    el('a', { href: `#/article/${slug}`, 'data-link': '' }, '← Back to the article')));
  body.append(el('h1', { style: { fontSize: '32px', marginBottom: '6px' } }, 'Explore connections'));
  body.append(el('p', { style: { color: 'var(--ink-2)', marginBottom: '20px' } },
    'Drag to pan, scroll to zoom, click a topic to open it.'));

  if (!data.nodes.length) {
    body.append(el('div', { class: 'empty' }, el('h2', {}, 'No connections recorded yet')));
    return root;
  }

  const W = 1000, H = 560;
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `Knowledge graph around ${slug}`);

  // Radial layout rather than a force simulation: depth picks the ring and
  // position within the depth picks the angle. Deterministic, no physics loop,
  // and it keeps the focus article visually central.
  const byDepth = new Map();
  for (const node of data.nodes) {
    if (!byDepth.has(node.depth)) byDepth.set(node.depth, []);
    byDepth.get(node.depth).push(node);
  }
  const pos = new Map();
  for (const [depth, nodes] of byDepth) {
    const radius = depth === 0 ? 0 : 110 + depth * 105;
    nodes.forEach((node, index) => {
      const angle = (index / nodes.length) * Math.PI * 2 - Math.PI / 2;
      pos.set(node.id, {
        x: W / 2 + Math.cos(angle) * radius,
        y: H / 2 + Math.sin(angle) * radius * 0.78,
      });
    });
  }

  const viewport = document.createElementNS(svgNS, 'g');
  svg.append(viewport);

  for (const edge of data.edges) {
    const a = pos.get(edge.source), b = pos.get(edge.target);
    if (!a || !b) continue;
    const line = document.createElementNS(svgNS, 'line');
    line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
    line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
    line.setAttribute('class', 'gedge');
    viewport.append(line);
  }

  for (const node of data.nodes) {
    const p = pos.get(node.id);
    const group = document.createElementNS(svgNS, 'g');
    group.setAttribute('class', `gnode${node.depth === 0 ? ' root' : ''}`);
    group.setAttribute('transform', `translate(${p.x},${p.y})`);
    group.style.cursor = 'pointer';
    group.addEventListener('click', () => go(`#/article/${node.slug}`));

    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('r', node.depth === 0 ? 34 : 26);
    group.append(circle);

    const label = document.createElementNS(svgNS, 'text');
    label.setAttribute('y', node.depth === 0 ? 54 : 44);
    label.textContent = node.title.length > 22 ? `${node.title.slice(0, 21)}…` : node.title;
    group.append(label);

    const title = document.createElementNS(svgNS, 'title');
    title.textContent = node.title;
    group.append(title);
    viewport.append(group);
  }

  // pan + zoom
  let scale = 1, tx = 0, ty = 0, dragging = false, lastX = 0, lastY = 0;
  const apply = () => viewport.setAttribute('transform', `translate(${tx},${ty}) scale(${scale})`);
  svg.addEventListener('pointerdown', (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY; svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    tx += e.clientX - lastX; ty += e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY; apply();
  });
  svg.addEventListener('pointerup', () => { dragging = false; });
  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    scale = Math.min(2.5, Math.max(0.4, scale * (e.deltaY > 0 ? 0.9 : 1.1)));
    apply();
  }, { passive: false });

  body.append(el('div', { class: 'graph-stage' }, svg));
  body.append(el('p', { style: { marginTop: '14px', fontSize: '13px', color: 'var(--ink-3)' } },
    `${data.nodes.length} topics, ${data.edges.length} connections.`));
  return root;
}

/* ----------------------------------------------------------------- paths -- */
export async function pathsView() {
  const rows = await api.paths();
  return wrap(el('div', { style: { padding: '34px 0 60px' } },
    el('h1', { style: { fontSize: '34px', marginBottom: '8px' } }, 'Learning paths'),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '24px' } },
      'Each path walks through a set of articles in an order that builds on itself.'),
    el('div', { class: 'grid cols-3' }, rows.map((p) =>
      el('a', { class: 'card', href: `#/path/${p.key}`, 'data-link': '' },
        el('div', { class: 'card-body' },
          el('div', { style: { fontSize: '30px' } }, p.icon || '🧭'),
          el('h3', {}, p.title),
          el('p', { class: 'desc' }, p.description),
          el('div', { class: 'meta' },
            el('span', { class: 'badge accent' }, `${p.steps} steps`),
            el('span', {}, levelLabel(p.age_band))),
        ))),
    )));
}

export async function pathView(key) {
  const data = await api.path(key);
  return wrap(el('div', { style: { padding: '34px 0 60px', maxWidth: '760px' } },
    el('div', { style: { fontSize: '40px' } }, data.icon || '🧭'),
    el('h1', { style: { fontSize: '34px', margin: '6px 0 8px' } }, data.title),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '26px' } }, data.description),
    el('div', { class: 'timeline' }, data.steps.map((s, i) =>
      el('div', { class: 'tl-item' },
        el('div', { class: 'tl-era' }, `Step ${i + 1}`),
        el('h3', {}, el('a', { href: `#/article/${s.slug}`, 'data-link': '',
          style: { color: 'inherit', textDecoration: 'none' } }, s.title)),
        el('p', {}, excerpt(s.summary, 170)),
      ))),
  ));
}

/* ------------------------------------------------------------------ quiz -- */
export async function quizView(key) {
  const data = await api.quiz(key);
  const root = wrap(el('div', { style: { padding: '34px 0 60px' } }));
  const body = root.firstChild;
  let index = 0, score = 0;

  const render = () => {
    body.replaceChildren();
    if (index >= data.questions.length) {
      body.append(el('div', { class: 'quiz-card' },
        el('h1', { style: { fontSize: '28px', marginBottom: '10px' } }, 'Finished'),
        el('p', { style: { fontSize: '19px' } },
          `You scored ${score} out of ${data.questions.length}.`),
        el('div', { style: { display: 'flex', gap: '10px', marginTop: '18px' } },
          el('button', { class: 'btn', onclick: () => { index = 0; score = 0; render(); } }, 'Try again'),
          el('a', { class: 'btn ghost', href: '#/', 'data-link': '' }, 'Back to home')),
      ));
      return;
    }

    const question = data.questions[index];
    const card = el('div', { class: 'quiz-card' },
      el('div', { class: 'quiz-progress' },
        `Question ${index + 1} of ${data.questions.length} · ${question.difficulty}`),
      el('h2', { class: 'quiz-q' }, question.prompt),
    );

    const buttons = [];
    // Options are shuffled per render so the correct answer is not positional.
    const options = [...question.options].sort(() => Math.random() - 0.5);
    for (const option of options) {
      const button = el('button', { class: 'opt' }, option.text);
      button.addEventListener('click', () => {
        for (const other of buttons) other.disabled = true;
        if (option.is_correct) { button.classList.add('correct'); score += 1; }
        else {
          button.classList.add('wrong');
          const right = buttons.find((b, i) => options[i].is_correct);
          right?.classList.add('correct');
        }
        card.append(el('div', { class: 'explain' }, question.explanation));
        if (question.article_slug) {
          card.append(el('p', { style: { marginTop: '12px', fontSize: '13.5px' } },
            'Read more: ',
            el('a', { href: `#/article/${question.article_slug}`, 'data-link': '' },
              question.article_slug.replace(/-/g, ' '))));
        }
        card.append(el('button', { class: 'btn', style: { marginTop: '16px' },
          onclick: () => { index += 1; render(); } },
          index + 1 < data.questions.length ? 'Next question' : 'See result'));
      });
      buttons.push(button);
      card.append(button);
    }
    body.append(el('h1', { style: { fontSize: '28px', marginBottom: '16px' } }, data.title), card);
  };

  render();
  return root;
}

/* --------------------------------------------------------------- compare -- */
export async function compareView(slugsText) {
  const slugs = slugsText.split(',').map((s) => s.trim()).filter(Boolean);
  if (slugs.length < 2) {
    return wrap(el('div', { class: 'empty', style: { marginTop: '40px' } },
      el('h2', {}, 'Pick two topics to compare'),
      el('p', {}, 'Try #/compare/tyrannosaurus-rex,blue-whale')));
  }
  const data = await api.compare(slugs);
  const table = el('table', { class: 'cmp' },
    el('thead', {}, el('tr', {}, el('th', {}, ''),
      data.articles.map((a) => el('th', {},
        el('a', { href: `#/article/${a.slug}`, 'data-link': '' }, a.title))))),
    el('tbody', {}, data.rows.map((row) => el('tr', {},
      el('th', { scope: 'row' }, row.label),
      data.articles.map((a) => {
        const value = row.values[a.slug];
        if (!value) return el('td', { style: { color: 'var(--ink-3)' } }, '—');
        const best = row.max != null && value.num === row.max;
        return el('td', { class: best ? 'best' : '' }, value.text,
          value.epistemic && value.epistemic !== 'fact'
            ? el('span', { class: 'badge amber', style: { marginLeft: '6px' } }, 'est.') : null);
      }),
    ))),
  );
  return wrap(el('div', { style: { padding: '34px 0 60px' } },
    el('h1', { style: { fontSize: '32px', marginBottom: '6px' } }, 'Compare'),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '22px' } },
      'Only dimensions both subjects actually record are shown. Estimates are marked.'),
    el('div', { class: 'scroll-x' }, table),
  ));
}

/* ------------------------------------------------------------------- ask -- */
export async function askView(prefill = '') {
  const root = wrap(el('div', { style: { padding: '34px 0 60px', maxWidth: '760px' } }));
  const body = root.firstChild;
  const answer = el('div');

  const ask = async (question) => {
    answer.replaceChildren(spinner());
    try {
      const data = await api.ask(question, state.level);
      answer.replaceChildren(renderAnswer(data));
    } catch (error) {
      answer.replaceChildren(el('div', { class: 'notice' }, error.message));
    }
  };

  body.append(
    el('h1', { style: { fontSize: '34px', marginBottom: '8px' } }, 'Ask the encyclopaedia'),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '20px' } },
      'Answers are built only from articles in this encyclopaedia and the sources they cite. '
      + 'If nothing here covers your question, it will say so rather than guess.'),
    el('form', {
      style: { display: 'flex', gap: '10px', marginBottom: '24px' },
      onsubmit: (e) => { e.preventDefault(); const v = e.target.elements.aq.value.trim(); if (v) ask(v); },
    },
      el('input', { name: 'aq', type: 'text', value: prefill,
        placeholder: 'Why did the dinosaurs die out?',
        style: { flex: '1', padding: '12px 16px', fontSize: '15px',
          border: '1px solid var(--line-strong)', borderRadius: 'var(--r-md)',
          background: 'var(--surface)', color: 'var(--ink)' } }),
      el('button', { class: 'btn', type: 'submit' }, 'Ask'),
    ),
    answer,
  );
  if (prefill) ask(prefill);
  return root;
}

function renderAnswer(data) {
  const out = el('div');

  if (data.answered) {
    out.append(el('div', { class: 'prose', style: { fontSize: '17px' } },
      renderMarkdown(data.answer)));
    out.append(el('div', { class: 'notice' }, data.disclaimer));
    if (data.invalid_citations?.length) {
      out.append(el('div', { class: 'notice', style: { background: 'var(--rose-soft)', color: 'var(--rose)' } },
        `The model referred to passages that do not exist (${data.invalid_citations.join(', ')}). `
        + 'Treat this answer with caution.'));
    }
  } else {
    out.append(el('div', { class: 'notice' }, data.reason));
  }

  if (data.passages?.length) {
    out.append(el('h2', { style: { fontSize: '19px', margin: '26px 0 10px' } },
      data.answered ? 'Passages this answer is based on' : 'Articles that cover this'));
    for (const p of data.passages) {
      out.append(el('a', { class: 'result', href: `#/article/${p.slug}`, 'data-link': '' },
        el('div', { class: 'result-art', 'aria-hidden': 'true',
          style: { background: gradientFor(p.slug) } }, `P${p.number}`),
        el('div', {},
          el('div', { class: 'result-title' }, p.title),
          el('div', { class: 'result-desc' }, excerpt(p.excerpt, 190)),
          el('div', { class: 'result-meta' },
            el('span', { class: 'badge' }, levelLabel(p.reading_level)))),
      ));
    }
  }

  if (data.sources?.length) {
    out.append(el('h2', { style: { fontSize: '19px', margin: '26px 0 10px' } }, 'Sources'));
    out.append(el('div', {}, data.sources.map((s) => el('div', { class: 'source-item' },
      el('div', { class: 'source-num' }, String(s.tier)),
      el('div', {},
        el('div', { class: 'source-title' },
          s.url ? el('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title) : s.title),
        el('div', { class: 'source-meta' }, el('span', {}, s.publisher))),
    ))));
  }
  return out;
}

/* ----------------------------------------------------------------- admin -- */
export async function adminView() {
  const [dash, issues] = await Promise.all([api.dashboard(), api.issues()]);
  const s = dash.stats;
  return wrap(el('div', { style: { padding: '34px 0 60px' } },
    el('h1', { style: { fontSize: '32px', marginBottom: '6px' } }, 'Editorial dashboard'),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '24px' } },
      'Internal quality view. These numbers are for editors, not readers.'),
    el('div', { class: 'stat-row', style: { marginBottom: '30px' } },
      stat(s.articles, 'Published'),
      stat(s.needs_review, 'Due for review'),
      stat(s.proposals, 'AI proposals'),
      stat(s.errors, 'Open errors'),
      stat(s.warnings, 'Warnings'),
      stat(s.unverified_sources, 'Unverified links'),
      stat(s.avg_quality, 'Avg quality'),
    ),
    el('div', { class: 'grid cols-2' },
      el('div', { class: 'panel' }, el('header', {}, 'Lowest quality'),
        el('div', { class: 'rel-list' }, dash.lowest_quality.map((a) =>
          el('a', { class: 'rel-item', href: `#/article/${a.slug}`, 'data-link': '' },
            el('span', {}, a.title),
            el('span', { class: 'rel-kind' }, `${a.quality_score}/100`))))),
      el('div', { class: 'panel' }, el('header', {}, 'Next due for review'),
        el('div', { class: 'rel-list' }, dash.due_for_review.map((a) =>
          el('a', { class: 'rel-item', href: `#/article/${a.slug}`, 'data-link': '' },
            el('span', {}, a.title),
            el('span', { class: 'rel-kind' }, a.next_review_at))))),
    ),
    el('h2', { style: { fontSize: '21px', margin: '32px 0 12px' } },
      `Open issues (${issues.length})`),
    issues.length
      ? el('div', { class: 'panel' }, el('div', { class: 'rel-list' }, issues.slice(0, 40).map((i) =>
        el('div', { class: 'rel-item' },
          el('span', { class: `badge ${i.severity === 'error' ? 'rose' : 'amber'}` }, i.severity),
          el('span', {}, i.detail),
          el('span', { class: 'rel-kind' }, i.kind)))))
      : el('div', { class: 'empty' }, el('h2', {}, 'No open issues')),
    el('h2', { style: { fontSize: '21px', margin: '32px 0 12px' } }, 'Installed content packs'),
    el('div', { class: 'panel' }, el('div', { class: 'rel-list' }, dash.packs.map((p) =>
      el('div', { class: 'rel-item' },
        el('span', {}, `${p.title} ${p.version}`),
        el('span', { class: 'rel-kind' }, `${p.article_count} articles`))))),
  ));
}

/* ------------------------------------------------------------- bookmarks -- */
export async function bookmarksView() {
  const rows = await api.bookmarks();
  const [progress] = await Promise.all([api.continueReading().catch(() => [])]);
  return wrap(el('div', { style: { padding: '34px 0 60px' } },
    el('h1', { style: { fontSize: '32px', marginBottom: '6px' } }, 'Your library'),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '24px' } },
      'Saved on this device only. Nothing here is sent anywhere.'),
    progress.length ? frag(
      el('h2', { style: { fontSize: '20px', margin: '0 0 12px' } }, 'Continue reading'),
      el('div', { class: 'grid cols-3', style: { marginBottom: '30px' } },
        progress.map((p) => articleCard({ ...p, slug: p.slug }))),
    ) : null,
    el('h2', { style: { fontSize: '20px', margin: '0 0 12px' } }, 'Saved articles'),
    rows.length
      ? el('div', { class: 'grid cols-3' }, rows.map((r) => articleCard(
        { slug: r.article_slug, title: r.title || r.article_slug, summary: r.summary || '' })))
      : el('div', { class: 'empty' }, el('h2', {}, 'Nothing saved yet'),
        el('p', {}, 'Use “Save this article” on any page.')),
  ));
}

let rerender = () => {};
export function setRerender(fn) { rerender = fn; }
