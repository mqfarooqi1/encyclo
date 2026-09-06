/* Application shell: routing, header wiring, and mounting views. */

import { api, state, setKids, setTheme, applyTheme, onStateChange } from './api.js';
import { el, clear } from './dom.js';
import * as views from './views.js';

const main = document.getElementById('main');
const searchInput = document.getElementById('q');
const suggestBox = document.getElementById('suggest');

const ROUTES = [
  [/^\/?$/,                       () => views.homeView()],
  [/^\/search\/(.+)$/,            (m) => views.searchView(decodeURIComponent(m[1]))],
  [/^\/article\/([^/]+)$/,        (m) => views.articleView(m[1])],
  [/^\/history\/([^/]+)$/,        (m) => views.historyView(m[1])],
  [/^\/explore\/([^/]+)$/,        (m) => views.exploreView(m[1])],
  [/^\/category\/([^/]+)$/,       (m) => views.categoryView(m[1])],
  [/^\/categories$/,              () => views.categoriesView()],
  [/^\/timeline$/,                () => views.timelineView()],
  [/^\/paths$/,                   () => views.pathsView()],
  [/^\/path\/([^/]+)$/,           (m) => views.pathView(m[1])],
  [/^\/quiz\/([^/]+)$/,           (m) => views.quizView(m[1])],
  [/^\/compare\/(.+)$/,           (m) => views.compareView(decodeURIComponent(m[1]))],
  [/^\/ask(?:\/(.*))?$/,          (m) => views.askView(m[1] ? decodeURIComponent(m[1]) : '')],
  [/^\/library$/,                 () => views.bookmarksView()],
  [/^\/admin$/,                   () => views.adminView()],
];

const TABS = [
  ['#/', 'Home'],
  ['#/categories', 'Browse'],
  ['#/timeline', 'Timeline'],
  ['#/paths', 'Learning paths'],
  ['#/ask', 'Ask'],
  ['#/library', 'Library'],
  ['#/admin', 'Editorial'],
];

const KIDS_TABS = new Set(['#/', '#/categories', '#/timeline', '#/paths', '#/library']);

function renderTabs() {
  const bar = document.getElementById('tabs');
  const current = window.location.hash || '#/';
  clear(bar);
  for (const [href, label] of TABS) {
    if (state.kids && !KIDS_TABS.has(href)) continue;
    const active = href === '#/' ? current === '#/' || current === ''
      : current.startsWith(href);
    bar.append(el('a', { href, 'data-link': '', 'aria-current': active ? 'page' : null }, label));
  }
}

let currentToken = 0;

async function route() {
  const token = ++currentToken;
  const path = (window.location.hash || '#/').replace(/^#/, '') || '/';

  // "Surprise me" is a route rather than a button handler so it can be linked.
  if (path === '/random') {
    try {
      const article = await api.random();
      window.location.replace(`#/article/${article.slug}`);
    } catch { window.location.replace('#/'); }
    return;
  }

  renderTabs();
  clear(main).append(views.spinner());

  for (const [pattern, handler] of ROUTES) {
    const match = pattern.exec(path);
    if (!match) continue;
    try {
      const node = await handler(match);
      if (token !== currentToken) return;          // a newer navigation won
      clear(main).append(node);
    } catch (error) {
      if (token !== currentToken) return;
      clear(main).append(views.errorView(error));
    }
    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
    main.focus({ preventScroll: true });
    return;
  }
  clear(main).append(views.errorView(new Error(`No page at ${path}`)));
}

views.setRerender(route);

/* ------------------------------------------------------------ search box -- */
let suggestTimer = null;
let suggestIndex = -1;

function closeSuggestions() {
  suggestBox.hidden = true;
  suggestBox.replaceChildren();
  searchInput.setAttribute('aria-expanded', 'false');
  suggestIndex = -1;
}

async function updateSuggestions() {
  const value = searchInput.value.trim();
  if (value.length < 2) return closeSuggestions();
  let rows = [];
  try { rows = await api.autocomplete(value); } catch { return closeSuggestions(); }
  if (!rows.length) return closeSuggestions();

  suggestBox.className = 'suggestions';
  suggestBox.replaceChildren(...rows.map((row, i) => el('button', {
    type: 'button', role: 'option', id: `sug-${i}`, 'aria-selected': 'false',
    onclick: () => { closeSuggestions(); searchInput.value = ''; window.location.hash = `#/article/${row.slug}`; },
  }, el('span', { 'aria-hidden': 'true' }, row.icon || '📄'),
     el('span', {}, row.title),
     el('span', { class: 'stype' }, row.type_label))));
  suggestBox.hidden = false;
  searchInput.setAttribute('aria-expanded', 'true');
  suggestIndex = -1;
}

searchInput.addEventListener('input', () => {
  clearTimeout(suggestTimer);
  suggestTimer = setTimeout(updateSuggestions, 120);
});

searchInput.addEventListener('keydown', (event) => {
  const options = [...suggestBox.querySelectorAll('button')];
  if (event.key === 'Escape') { closeSuggestions(); return; }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    if (!options.length) return;
    event.preventDefault();
    suggestIndex = event.key === 'ArrowDown'
      ? (suggestIndex + 1) % options.length
      : (suggestIndex - 1 + options.length) % options.length;
    options.forEach((option, i) => option.setAttribute('aria-selected', String(i === suggestIndex)));
    searchInput.setAttribute('aria-activedescendant', `sug-${suggestIndex}`);
    return;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    if (suggestIndex >= 0 && options[suggestIndex]) { options[suggestIndex].click(); return; }
    const value = searchInput.value.trim();
    if (value) { closeSuggestions(); window.location.hash = `#/search/${encodeURIComponent(value)}`; }
  }
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('.searchbar')) closeSuggestions();
});

/* Keyboard shortcut: "/" focuses search, as in most reference tools. */
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName)) {
    event.preventDefault();
    searchInput.focus();
  }
});

/* ---------------------------------------------------------------- header -- */
const kidsButton = document.getElementById('kids');
kidsButton.setAttribute('aria-pressed', String(state.kids));
kidsButton.addEventListener('click', () => {
  setKids(!state.kids);
  kidsButton.setAttribute('aria-pressed', String(state.kids));
  document.documentElement.classList.toggle('kids-mode', state.kids);
  route();
});

document.getElementById('theme').addEventListener('click', () => {
  const order = ['system', 'light', 'dark'];
  setTheme(order[(order.indexOf(state.theme) + 1) % order.length]);
});

/* ---------------------------------------------------------------- status -- */
function renderStatus() {
  const flag = document.getElementById('net-flag');
  flag.classList.toggle('warn', !state.online);
  flag.lastElementChild.textContent = state.online
    ? 'Offline-capable · all content is local'
    : 'Cannot reach the local service';
}
onStateChange(renderStatus);

async function boot() {
  applyTheme();
  document.documentElement.classList.toggle('kids-mode', state.kids);
  renderStatus();
  window.addEventListener('hashchange', route);
  await route();

  try {
    const data = await api.bootstrap();
    state.bootstrap = data;
    const stats = data.stats || {};
    document.getElementById('foot-stats').textContent =
      `${stats.articles ?? 0} articles · ${stats.sources ?? 0} sources · pack “core”`;
    if (!data.capabilities?.ai) {
      // Never leave an AI control that silently does nothing.
      const askTab = document.querySelector('#tabs a[href="#/ask"]');
      if (askTab) askTab.title = 'No AI provider configured — answers fall back to cited articles';
    }
  } catch { /* the shell is useful even if bootstrap fails */ }
}

boot();
