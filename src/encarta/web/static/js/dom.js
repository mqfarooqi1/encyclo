/* Tiny DOM helpers.
   Everything is built as real nodes rather than by assigning innerHTML, so text
   coming from the database can never be interpreted as markup. */

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;      // only for trusted, locally built markup
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  append(node, children);
  return node;
}

export function append(parent, children) {
  for (const child of children.flat(4)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function frag(...children) {
  return append(document.createDocumentFragment(), children);
}

/* Deterministic pseudo-random covers.
   The seed pack ships no bitmap imagery, because we will not redistribute media
   whose licence we have not verified. Rather than leave grey boxes, each article
   gets a generated cover derived from its slug: stable across reloads, unique per
   article, and free of any third-party rights. */
export function hashString(text) {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

const PALETTES = [
  ['#0b6a6a', '#5b4a9e'], ['#a8620d', '#9c2f3f'], ['#2f6b3f', '#0b6a6a'],
  ['#5b4a9e', '#1f4f8f'], ['#9c2f3f', '#a8620d'], ['#1f4f8f', '#0b6a6a'],
  ['#7a3d7a', '#5b4a9e'], ['#8a5a1b', '#2f6b3f'],
];

export function coverFor(slug, icon) {
  const seed = hashString(slug || 'x');
  const [a, b] = PALETTES[seed % PALETTES.length];
  const angle = 90 + (seed >> 3) % 180;
  const node = el('div', {
    class: 'card-art',
    'aria-hidden': 'true',
    style: { background: `linear-gradient(${angle}deg, ${a}, ${b})` },
  });
  // A few translucent discs give the flat gradient some depth without assets.
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', '0 0 200 120');
  Object.assign(svg.style, { position: 'absolute', inset: '0', width: '100%', height: '100%' });
  for (let i = 0; i < 4; i++) {
    const s = (seed >> (i * 5)) & 0xff;
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', String(12 + (s % 180)));
    circle.setAttribute('cy', String(8 + ((s * 7) % 110)));
    circle.setAttribute('r', String(16 + (s % 40)));
    circle.setAttribute('fill', '#fff');
    circle.setAttribute('opacity', String(0.05 + ((s % 9) / 100)));
    svg.append(circle);
  }
  node.append(svg);
  if (icon) node.append(el('span', { style: { position: 'relative', filter: 'saturate(1.15)' } }, icon));
  return node;
}

export function gradientFor(slug) {
  const seed = hashString(slug || 'x');
  const [a, b] = PALETTES[seed % PALETTES.length];
  return `linear-gradient(${90 + (seed >> 3) % 180}deg, ${a}, ${b})`;
}
