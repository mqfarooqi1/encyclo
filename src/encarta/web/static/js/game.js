/* Explorer Trail, badges, awards, and read-aloud.

   The trail turns quizzing into a journey: stations unlock in sequence, each
   awards a badge, and progress is stored locally.

   One deliberate omission: there are no streaks, no daily targets and no
   notifications. Badges are earned for finishing something, never for coming
   back tomorrow. A child who has learned the material should have no reason to
   be pulled back by the software. */

import { api, state, levelLabel } from './api.js';
import { el, clear, gradientFor } from './dom.js';
import { quizRunner } from './quiz.js';

const go = (hash) => { window.location.hash = hash; };
const wrap = (...children) => el('div', { class: 'wrap' }, ...children);

function starRow(count, max = 3) {
  const row = el('span', { class: 'stars', 'aria-label': `${count} of ${max} stars` });
  for (let i = 0; i < max; i++) {
    row.append(el('span', { class: i < count ? '' : 'off', 'aria-hidden': 'true' }, '★'));
  }
  return row;
}

/* ------------------------------------------------------------ trail list -- */
export async function trailsView() {
  const trails = await api.trails();
  const badges = await api.badges().catch(() => []);
  const earned = badges.filter((b) => b.earned).length;

  return wrap(el('div', { style: { padding: '30px 0 60px' } },
    el('h1', { style: { fontSize: '34px', marginBottom: '6px' } }, 'Explorer Trails'),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '8px', maxWidth: '60ch' } },
      'Each trail is a line of stations. Answer the questions at a station to open '
      + 'the next one and collect its badge.'),
    badges.length ? el('p', { style: { marginBottom: '24px' } },
      el('a', { href: '#/badges', 'data-link': '', class: 'chip-btn' },
        `🏅 ${earned} of ${badges.length} badges collected`)) : null,

    trails.length ? el('div', { class: 'grid cols-2' }, trails.map((t) => {
      const pct = t.stations ? Math.round((t.completed / t.stations) * 100) : 0;
      return el('a', { class: 'card', href: `#/trail/${t.key}`, 'data-link': '' },
        el('div', { class: 'card-art', style: { background: gradientFor(t.key), height: '96px' },
          'aria-hidden': 'true' }, t.icon || '🧭'),
        el('div', { class: 'card-body' },
          el('h3', {}, t.title),
          el('p', { class: 'desc' }, t.description),
          el('div', { class: 'trail-meter', style: { margin: '10px 0 0' } },
            el('span', { class: 'bar' }, el('i', { style: { width: `${pct}%` } })),
            el('span', { style: { fontSize: '12.5px', color: 'var(--ink-3)' } },
              `${t.completed}/${t.stations}`)),
          el('div', { class: 'meta' },
            el('span', { class: 'badge' }, levelLabel(t.age_band)),
            starRow(Math.min(3, Math.round(t.stars / Math.max(1, t.stations))), 3)),
        ));
    })) : el('div', { class: 'empty' }, el('h2', {}, 'No trails for this age yet')),
  ));
}

/* ----------------------------------------------------------- trail board -- */
export async function trailView(key) {
  const trail = await api.trail(key);
  const pct = trail.stations.length
    ? Math.round((trail.completed / trail.stations.length) * 100) : 0;

  const board = el('div', { class: 'trail-board' });
  for (const station of trail.stations) {
    const locked = !station.unlocked;
    const cls = `station pal-${station.palette} ${locked ? 'locked' : ''} ${station.completed ? 'done' : ''}`;

    const inner = [
      el('div', { class: 'station-top' },
        el('span', { class: 'station-ico', 'aria-hidden': 'true' },
          locked ? '🔒' : station.icon),
        el('span', {},
          el('h3', {}, station.title),
          el('span', { class: 'sub' }, locked ? 'Finish the station before this one' : station.subtitle)),
      ),
      el('div', { class: 'station-foot' },
        station.completed ? starRow(station.stars) : el('span', {}, `${station.questions} questions`),
        station.badge_key && el('span', { style: { marginLeft: 'auto' } },
          station.badge_earned
            ? `${station.badge_icon} ${station.badge_title}`
            : `🔒 ${station.badge_title}`),
      ),
    ];

    board.append(locked
      ? el('div', { class: cls, 'aria-disabled': 'true' }, ...inner)
      : el('a', { class: cls, href: `#/station/${trail.key}/${station.key}`, 'data-link': '' },
          ...inner));
  }

  return wrap(el('div', { style: { paddingBottom: '50px' } },
    el('div', { class: 'crumbs', style: { paddingTop: '20px' } },
      el('a', { href: '#/trails', 'data-link': '' }, '← All trails')),
    el('div', { class: 'trail-head' },
      el('span', { class: 'mark', 'aria-hidden': 'true' }, trail.icon || '🧭'),
      el('div', {}, el('h1', {}, trail.title), el('p', {}, trail.description)),
    ),
    el('div', { class: 'trail-meter' },
      el('span', {}, `${trail.completed} of ${trail.stations.length} stations`),
      el('span', { class: 'bar' }, el('i', { style: { width: `${pct}%` } })),
      el('span', {}, `★ ${trail.stars}/${trail.max_stars}`),
    ),
    board,
    trail.completed === trail.stations.length && trail.stations.length
      ? el('div', { class: 'quiz-card', style: { textAlign: 'center' } },
          el('div', { style: { fontSize: '46px' } }, '🏆'),
          el('h2', { style: { fontSize: '23px', margin: '8px 0' } }, 'Trail complete'),
          el('p', { style: { color: 'var(--ink-2)' } },
            'Every station finished. Have a look at your badges.'),
          el('a', { class: 'btn', href: '#/badges', 'data-link': '',
            style: { marginTop: '12px' } }, 'See my badges'))
      : null,
  ));
}

/* --------------------------------------------------------- trail station -- */
export async function stationView(trailKey, stationKey) {
  const trail = await api.trail(trailKey);
  const station = trail.stations.find((s) => s.key === stationKey);
  if (!station) throw new Error('Unknown station');
  if (!station.unlocked) {
    return wrap(el('div', { class: 'empty', style: { marginTop: '40px' } },
      el('h2', {}, '🔒 Not open yet'),
      el('p', {}, 'Finish the station before this one first.'),
      el('a', { class: 'btn ghost', href: `#/trail/${trailKey}`, 'data-link': '',
        style: { marginTop: '14px' } }, 'Back to the trail')));
  }

  const quiz = await api.quiz(station.quiz_key);
  const root = wrap(el('div', { style: { padding: '26px 0 60px' } }));
  const body = root.firstChild;

  body.append(el('div', { class: 'crumbs', style: { marginBottom: '14px' } },
    el('a', { href: `#/trail/${trailKey}`, 'data-link': '' }, `← ${trail.title}`),
    station.article_slug && el('span', { 'aria-hidden': 'true' }, '·'),
    station.article_slug && el('a', { href: `#/article/${station.article_slug}`, 'data-link': '' },
      `Read ${station.article_title} first`),
  ));

  body.append(quizRunner(quiz, {
    subtitle: `${station.icon} ${station.title} — ${station.subtitle}`,
    onFinish: async (score, total) => {
      try {
        const result = await api.recordStation(trailKey, stationKey, score, total);
        if (result.badges_awarded?.length) await showAwards(result.badges_awarded);
        body.append(el('div', { style: { marginTop: '18px', display: 'flex', gap: '10px',
          justifyContent: 'center', flexWrap: 'wrap' } },
          el('a', { class: 'btn', href: `#/trail/${trailKey}`, 'data-link': '' },
            result.passed ? 'Back to the trail →' : 'Back to the trail'),
          station.article_slug && el('a', {
            class: 'btn ghost', href: `#/article/${station.article_slug}`, 'data-link': '',
          }, 'Read the article'),
        ));
      } catch {
        body.append(el('div', { class: 'notice', style: { marginTop: '16px' } },
          'Your score could not be saved, but the answers above are still right.'));
      }
    },
  }));
  return root;
}

/* ---------------------------------------------------------------- awards -- */
function confetti() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const colours = ['#0b6a6a', '#a8620d', '#9c2f3f', '#5b4a9e', '#2f7d55'];
  for (let i = 0; i < 40; i++) {
    const dot = el('span', { class: 'confetti-dot', style: {
      left: `${Math.random() * 100}vw`,
      top: `${-10 - Math.random() * 20}vh`,
      background: colours[i % colours.length],
      animationDuration: `${1.6 + Math.random() * 1.4}s`,
      animationDelay: `${Math.random() * 0.4}s`,
    } });
    document.body.append(dot);
    setTimeout(() => dot.remove(), 3600);
  }
}

/** Shows each awarded badge in turn; resolves when the reader dismisses them. */
export function showAwards(badges) {
  return badges.reduce(
    (chain, badge) => chain.then(() => new Promise((resolve) => {
      const close = () => { veil.remove(); document.removeEventListener('keydown', onKey); resolve(); };
      const onKey = (e) => { if (e.key === 'Escape' || e.key === 'Enter') close(); };
      const veil = el('div', {
        class: 'award-veil', role: 'dialog', 'aria-modal': 'true',
        'aria-label': `Badge earned: ${badge.title}`,
        onclick: (e) => { if (e.target === veil) close(); },
      }, el('div', { class: 'award' },
        el('div', { class: 'eyebrow' }, 'Badge earned'),
        el('span', { class: 'a-ico', 'aria-hidden': 'true' }, badge.icon),
        el('h2', {}, badge.title),
        el('p', {}, badge.description),
        el('button', { class: 'btn', style: { marginTop: '18px' }, onclick: close }, 'Nice!'),
      ));
      document.body.append(veil);
      veil.querySelector('button').focus();
      document.addEventListener('keydown', onKey);
      confetti();
    })),
    Promise.resolve(),
  );
}

/* --------------------------------------------------------------- badges -- */
export async function badgesView() {
  const badges = await api.badges();
  const earned = badges.filter((b) => b.earned);

  return wrap(el('div', { style: { padding: '30px 0 60px' } },
    el('h1', { style: { fontSize: '34px', marginBottom: '6px' } }, 'Badge cabinet'),
    el('p', { style: { color: 'var(--ink-2)', marginBottom: '22px' } },
      `${earned.length} of ${badges.length} collected. Badges are kept on this device only.`),
    el('div', { class: 'badge-grid' }, badges.map((b) =>
      el('div', { class: `badge-card ${b.earned ? 'earned' : ''}`,
        title: b.earned ? `Earned ${b.earned_at}` : b.criteria },
        el('span', { class: 'b-ico', 'aria-hidden': 'true' }, b.icon),
        el('strong', {}, b.title),
        el('span', {}, b.earned ? b.description : b.criteria),
      ))),
    el('p', { style: { marginTop: '28px' } },
      el('button', {
        class: 'chip-btn',
        onclick: async (e) => {
          if (e.target.dataset.armed !== '1') {
            e.target.dataset.armed = '1';
            e.target.textContent = 'Tap again to clear all progress';
            return;
          }
          await api.resetTrails();
          go('#/trails');
        },
      }, 'Start all trails again')),
  ));
}

/* ------------------------------------------------------------ read aloud -- */
/* Uses the browser's own speech synthesis, which runs on the device and needs
   no network. Where a browser has no voices installed the control disables
   itself and says why, rather than appearing to work. */

let speaking = null;

export function speechAvailable() {
  return typeof window.speechSynthesis !== 'undefined';
}

export function stopSpeech() {
  if (speechAvailable()) window.speechSynthesis.cancel();
  speaking = null;
}

export function readAloudButton(getText, label = 'Read aloud') {
  const button = el('button', { class: 'aloud', type: 'button', 'aria-pressed': 'false' },
    el('span', { 'aria-hidden': 'true' }, '🔊'), el('span', {}, label));

  if (!speechAvailable()) {
    button.disabled = true;
    button.title = 'This browser cannot read text aloud';
    button.lastChild.textContent = 'Read aloud unavailable';
    return button;
  }

  button.addEventListener('click', () => {
    if (speaking) {
      stopSpeech();
      button.setAttribute('aria-pressed', 'false');
      button.lastChild.textContent = label;
      return;
    }
    const utterance = new SpeechSynthesisUtterance(getText());
    utterance.rate = state.kids ? 0.88 : 1.0;
    utterance.onend = () => {
      speaking = null;
      button.setAttribute('aria-pressed', 'false');
      button.lastChild.textContent = label;
    };
    speaking = utterance;
    window.speechSynthesis.speak(utterance);
    button.setAttribute('aria-pressed', 'true');
    button.lastChild.textContent = 'Stop';
  });
  return button;
}

/* ------------------------------------------------- size comparison strip -- */
/* Built from facts that share a comparable_key, so it works for any article
   carrying one — no per-article configuration. */

const REFERENCES = {
  body_length: [
    { label: 'You (a child)', value: 1.4 },
    { label: 'A car', value: 4.5 },
    { label: 'A bus', value: 12 },
  ],
  body_mass: [
    { label: 'A person', value: 70 },
    { label: 'A car', value: 1500 },
    { label: 'An elephant', value: 6000 },
  ],
  diameter: [{ label: 'Earth', value: 12742 }],
};

export function sizeStrip(facts, title) {
  const fact = facts.find((f) => f.comparable_key && REFERENCES[f.comparable_key] && f.value_num);
  if (!fact) return null;

  const rows = [
    { label: title, value: Number(fact.value_num), self: true },
    ...REFERENCES[fact.comparable_key],
  ].sort((a, b) => b.value - a.value);
  const max = rows[0].value;
  const unit = fact.unit || '';

  return el('div', { class: 'panel' },
    el('header', {}, `How big? (${fact.label.toLowerCase()})`),
    el('div', { class: 'body' },
      el('div', { class: 'sizebar' }, rows.map((row) =>
        el('div', { class: `size-row ${row.self ? 'self' : ''}` },
          el('span', { class: 'lbl' }, row.label),
          el('span', { class: 'track' },
            el('span', { class: 'fill', style: { width: `${Math.max(2, (row.value / max) * 100)}%` } })),
          el('span', { class: 'val' }, `${row.value.toLocaleString()} ${unit}`),
        ))),
      fact.epistemic !== 'fact' && el('p', {
        style: { fontSize: '12px', color: 'var(--ink-3)', marginTop: '10px', marginBottom: 0 },
      }, 'The highlighted figure is an estimate, so treat the comparison as rough.'),
    ),
  );
}

export { clear };
