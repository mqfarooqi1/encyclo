/* API client and shared UI state.

   Every request is same-origin and works with the machine offline. Network
   failure is surfaced honestly through `netStatus` rather than being retried
   silently or hidden behind a spinner that never resolves. */

const listeners = new Set();

export const state = {
  kids: localStorage.getItem('encarta.kids') === '1',
  level: localStorage.getItem('encarta.level') || 'adult',
  theme: localStorage.getItem('encarta.theme') || 'system',
  bootstrap: null,
  online: true,
};

export function onStateChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit() { for (const fn of listeners) fn(state); }

export function setKids(value) {
  state.kids = value;
  localStorage.setItem('encarta.kids', value ? '1' : '0');
  // Kids Mode implies a reading level appropriate to it.
  if (value && (state.level === 'adult' || state.level === 'teen')) setLevel('age9_12');
  emit();
}

export function setLevel(value) {
  state.level = value;
  localStorage.setItem('encarta.level', value);
  emit();
}

export function setTheme(value) {
  state.theme = value;
  localStorage.setItem('encarta.theme', value);
  applyTheme();
  emit();
}

export function applyTheme() {
  const root = document.documentElement;
  if (state.theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', state.theme);
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch {
    state.online = false;
    emit();
    throw new ApiError('Cannot reach the encyclopaedia service. Is it still running?', 0);
  }
  if (!state.online) { state.online = true; emit(); }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { detail = (await response.json()).error || detail; } catch { /* keep default */ }
    throw new ApiError(detail, response.status);
  }
  return response.json();
}

const qs = (params) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '' || value === false) continue;
    search.set(key, value === true ? '1' : String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
};

const kids = () => (state.kids ? { kids: 1 } : {});

export const api = {
  bootstrap: () => request(`/api/bootstrap${qs(kids())}`),
  home: () => request(`/api/home${qs(kids())}`),
  search: (q, extra = {}) => request(`/api/search${qs({ q, ...kids(), ...extra })}`),
  autocomplete: (q) => request(`/api/autocomplete${qs({ q, ...kids() })}`),
  article: (slug, level) => request(`/api/article/${encodeURIComponent(slug)}${qs({ level, ...kids() })}`),
  graph: (slug, depth = 2) => request(`/api/article/${encodeURIComponent(slug)}/graph${qs({ depth })}`),
  versions: (slug) => request(`/api/article/${encodeURIComponent(slug)}/versions`),
  quality: (slug) => request(`/api/article/${encodeURIComponent(slug)}/quality`),
  category: (key) => request(`/api/category/${encodeURIComponent(key)}${qs(kids())}`),
  categories: () => request(`/api/categories${qs(kids())}`),
  timeline: (params = {}) => request(`/api/timeline${qs(params)}`),
  places: () => request(`/api/places${qs(kids())}`),
  paths: () => request(`/api/paths${qs(kids())}`),
  path: (key) => request(`/api/path/${encodeURIComponent(key)}`),
  quiz: (key) => request(`/api/quiz/${encodeURIComponent(key)}`),
  random: (category) => request(`/api/random${qs({ category, ...kids() })}`),
  compare: (slugs) => request(`/api/compare${qs({ slugs: slugs.join(',') })}`),
  source: (uid) => request(`/api/source/${encodeURIComponent(uid)}`),
  ask: (question, level) => request('/api/ask', {
    method: 'POST',
    body: JSON.stringify({ question, level, kids: state.kids }),
  }),
  bookmarks: () => request('/api/bookmarks'),
  addBookmark: (slug) => request('/api/bookmarks', { method: 'POST', body: JSON.stringify({ slug }) }),
  removeBookmark: (slug) => request(`/api/bookmarks/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
  saveProgress: (slug, level, scroll) => request('/api/progress', {
    method: 'POST', body: JSON.stringify({ slug, level, scroll }),
  }),
  continueReading: () => request('/api/continue'),
  dashboard: () => request('/api/admin/dashboard'),
  issues: (severity) => request(`/api/admin/issues${qs({ severity })}`),
};

/** Format a signed year for the deep-time timeline. */
export function formatYear(year) {
  const value = Number(year);
  if (!Number.isFinite(value)) return '';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(abs / 1e9).toFixed(2).replace(/\.?0+$/, '')} billion years ago`;
  if (abs >= 1e6) return `${(abs / 1e6).toFixed(1).replace(/\.0$/, '')} million years ago`;
  if (abs >= 10000) return `${Math.round(abs / 1000)},000 years ago`;
  if (value < 0) return `${Math.round(abs)} BCE`;
  return String(Math.round(value));
}

export function levelLabel(key) {
  return {
    age6_8: 'Ages 6–8', age9_12: 'Ages 9–12', teen: 'Teen', adult: 'Adult',
  }[key] || key;
}
