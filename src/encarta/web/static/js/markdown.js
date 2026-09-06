/* A deliberately small Markdown subset renderer.

   Article bodies use only headings, paragraphs, lists, bold, italic and the
   [n] citation markers. Rather than pull in a full Markdown library — which
   would mean shipping a third-party parser and its HTML-injection surface into
   an app children use — this renders that subset directly to DOM nodes.

   Nothing here ever produces HTML from a string, so a stray angle bracket in an
   article is text, not markup. */

import { el, append } from './dom.js';

const CITE = /\[(\d{1,3})\]/g;
const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|\[\d{1,3}\])/g;

function renderInline(text, onCite) {
  const out = [];
  for (const part of text.split(INLINE)) {
    if (!part) continue;
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      out.push(el('strong', {}, part.slice(2, -2)));
    } else if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      out.push(el('em', {}, part.slice(1, -1)));
    } else {
      const match = /^\[(\d{1,3})\]$/.exec(part);
      if (match) {
        const n = Number(match[1]);
        out.push(el('a', {
          class: 'cite',
          href: `#source-${n}`,
          title: 'Jump to the source for this claim',
          onclick: (event) => { event.preventDefault(); onCite?.(n); },
        }, String(n)));
      } else {
        out.push(document.createTextNode(part));
      }
    }
  }
  return out;
}

export function renderMarkdown(source, { onCite } = {}) {
  const root = document.createDocumentFragment();
  const lines = String(source || '').replace(/\r\n/g, '\n').split('\n');
  let list = null;

  const closeList = () => { if (list) { root.append(list); list = null; } };

  for (const raw of lines) {
    const line = raw.trimEnd();

    if (!line.trim()) { closeList(); continue; }

    const heading = /^(#{2,4})\s+(.*)$/.exec(line);
    if (heading) {
      closeList();
      root.append(el(`h${heading[1].length}`, {}, ...renderInline(heading[2], onCite)));
      continue;
    }

    const bullet = /^[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      if (!list || list.tagName !== 'UL') { closeList(); list = el('ul'); }
      list.append(el('li', {}, ...renderInline(bullet[1], onCite)));
      continue;
    }

    const numbered = /^(\d+)\.\s+(.*)$/.exec(line);
    if (numbered) {
      if (!list || list.tagName !== 'OL') { closeList(); list = el('ol'); }
      list.append(el('li', {}, ...renderInline(numbered[2], onCite)));
      continue;
    }

    closeList();
    root.append(el('p', {}, ...renderInline(line, onCite)));
  }
  closeList();
  return root;
}

/** Plain-text excerpt with markdown stripped, for cards and previews. */
export function excerpt(source, maxChars = 180) {
  const text = String(source || '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*?/g, '')
    .replace(CITE, '')
    .replace(/\s+/g, ' ')
    .trim();
  return text.length > maxChars ? `${text.slice(0, maxChars).trimEnd()}…` : text;
}

/** Renders a search snippet, which the server marks up with <mark> only. */
export function renderSnippet(snippet) {
  const node = el('div', { class: 'result-desc' });
  const parts = String(snippet || '').split(/(<\/?mark>)/);
  let marking = false;
  for (const part of parts) {
    if (part === '<mark>') { marking = true; continue; }
    if (part === '</mark>') { marking = false; continue; }
    if (!part) continue;
    append(node, [marking ? el('mark', {}, part) : document.createTextNode(part)]);
  }
  return node;
}
