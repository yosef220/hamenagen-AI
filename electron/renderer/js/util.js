'use strict';

/*
 * Shared helpers. Every renderer script hangs off one namespace, `H`, and is
 * a plain classic script (the page's CSP allows only local scripts).
 */
const H = (window.H = window.H || {});

H.$ = (sel, root = document) => root.querySelector(sel);
H.$$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const SVG_NS = 'http://www.w3.org/2000/svg';

/** An icon from the bundled Lucide sprite. */
H.icon = function icon(name, cls) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', cls ? `icon ${cls}` : 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `vendor/icons.svg#${name}`);
  svg.appendChild(use);
  return svg;
};

/** Swap the icon inside a button (or any element holding one). */
H.setIcon = function setIcon(host, name) {
  const use = host.querySelector('use');
  if (use) use.setAttribute('href', `vendor/icons.svg#${name}`);
};

/**
 * Build an element: h('button', { class: 'btn', onclick: fn, 'aria-label': 'x' }, 'text', child).
 * Attribute values of `false`/`null` are skipped; strings become text nodes.
 */
H.h = function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === false || value === null || value === undefined) continue;
    if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2), value);
    } else if (key === 'class') {
      node.className = value;
    } else if (key === 'text') {
      node.textContent = value;
    } else if (key === 'dataset') {
      Object.assign(node.dataset, value);
    } else if (key === 'style') {
      for (const [prop, v] of Object.entries(value)) node.style.setProperty(prop, v);
    } else if (value === true) {
      node.setAttribute(key, '');
    } else {
      node.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === 'string' || typeof child === 'number' ? document.createTextNode(String(child)) : child);
  }
  return node;
};

H.clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); return node; };

H.debounce = function debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
};

// ------------------------------------------------------------ Hebrew words
const nf = new Intl.NumberFormat('he-IL');
H.n = (x) => nf.format(Math.round(x || 0));

/** "שיר אחד" / "2 שירים" / "1,284 שירים". */
H.songs = (n) => (n === 1 ? 'שיר אחד' : `${H.n(n)} שירים`);
H.channels = (n) => (n === 1 ? 'ערוץ אחד' : `${H.n(n)} ערוצים`);
H.days = (n) => (n === 1 ? 'מחר' : n === 2 ? 'בעוד יומיים' : `בעוד ${H.n(n)} ימים`);

/** 245 → "4:05"; 3725 → "1:02:05". */
H.clock = function clock(sec) {
  if (!Number.isFinite(sec) || sec < 0) return '0:00';
  const s = Math.floor(sec % 60);
  const m = Math.floor(sec / 60) % 60;
  const hr = Math.floor(sec / 3600);
  const ss = String(s).padStart(2, '0');
  return hr ? `${hr}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
};

/** A length in words: "58 דקות", "שעה ורבע", "3 שעות ו-10 דקות". */
H.span = function span(sec) {
  const total = Math.round((sec || 0) / 60);
  if (total < 1) return 'פחות מדקה';
  if (total < 60) return total === 1 ? 'דקה' : `${total} דקות`;
  const hr = Math.floor(total / 60);
  const min = total % 60;
  const hours = hr === 1 ? 'שעה' : hr === 2 ? 'שעתיים' : `${hr} שעות`;
  if (!min) return hours;
  if (min === 15) return `${hours} ורבע`;
  if (min === 30) return `${hours} וחצי`;
  return `${hours} ו-${min === 1 ? 'דקה' : `${min} דקות`}`;
};

/** "לפני 3 דקות" / "היום ב-14:05" / "אתמול" / "12 בנובמבר". */
H.ago = function ago(iso) {
  if (!iso) return '';
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return '';
  const diff = (Date.now() - then.getTime()) / 1000;
  if (diff < 60) return 'ממש עכשיו';
  if (diff < 3600) {
    const m = Math.round(diff / 60);
    return m === 1 ? 'לפני דקה' : `לפני ${m} דקות`;
  }
  const today = new Date();
  const time = then.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
  if (then.toDateString() === today.toDateString()) return `היום ב-${time}`;
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  if (then.toDateString() === y.toDateString()) return `אתמול ב-${time}`;
  return then.toLocaleDateString('he-IL', { day: 'numeric', month: 'long' });
};

H.civilDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('he-IL', { day: 'numeric', month: 'long', year: 'numeric' });

// ------------------------------------------------------- topics and covers
H.TOPIC_TINTS = {
  'שבת': 'gold',
  'ראש השנה': 'wine',
  'יום כיפור': 'slate',
  'סוכות': 'cedar',
  'חנוכה': 'tekhelet',
  'פורים': 'wine',
  'פסח': 'stone',
  'ל״ג בעומר': 'ember',
  'שבועות': 'cedar',
  'אלול': 'slate',
  'חתונה': 'wine',
  'ירושלים': 'stone',
  'אמונה': 'tekhelet',
  'ווקאלי': 'ink',
};
H.tint = (topic) => H.TOPIC_TINTS[topic] || 'none';

const FINALS = { 'ך': 'כ', 'ם': 'מ', 'ן': 'נ', 'ף': 'פ', 'ץ': 'צ' };

/** The letter a song or topic is drawn with: its first Hebrew letter. */
H.letter = function letter(text) {
  const s = String(text || '').normalize('NFC');
  const heb = s.match(/[א-ת]/);
  if (heb) return FINALS[heb[0]] || heb[0];
  const latin = s.match(/[A-Za-z0-9]/);
  return latin ? latin[0].toUpperCase() : '♪';
};

H.trackTitle = (t) => (t && (t.title || (t.filename || '').replace(/\.[^.]+$/, ''))) || 'ללא שם';

// ------------------------------------------------------------------ toasts
H.toast = function toast(text, opts = {}) {
  const host = H.$('#toasts');
  const node = H.h(
    'div',
    { class: `toast ${opts.kind || ''}`, role: opts.kind === 'bad' ? 'alert' : 'status' },
    opts.icon ? H.icon(opts.icon) : opts.kind === 'bad' ? H.icon('circle-alert') : null,
    H.h('span', { text }),
    opts.action ? H.h('button', { type: 'button', onclick: () => { opts.action.fn(); node.remove(); } }, opts.action.label) : null,
  );
  host.appendChild(node);
  setTimeout(() => node.remove(), opts.ms || 4200);
  return node;
};

/** Keep a range input's filled part in step with its value. */
H.fillRange = function fillRange(input) {
  const min = Number(input.min || 0);
  const max = Number(input.max || 100);
  const pct = max > min ? ((Number(input.value) - min) / (max - min)) * 100 : 0;
  input.style.setProperty('--fill', `${pct}%`);
};

H.storage = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem(`hamenagen.${key}`);
      return v === null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try { localStorage.setItem(`hamenagen.${key}`, JSON.stringify(value)); } catch { /* private mode */ }
  },
};
