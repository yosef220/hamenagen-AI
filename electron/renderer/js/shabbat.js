'use strict';

/*
 * Shabbat and festival mode.
 *
 * The core (zmanim.py) knows the times for the listener's city; the clock
 * here picks the moment. Half an hour before, a note says when the music will
 * stop; a minute before, it fades to silence; then "שבת שלום" covers the
 * window until Shabbat (or the festival) ends, and nothing plays meanwhile.
 * Someone who does not keep Shabbat on this computer can turn it off from the
 * screen itself.
 */
(function () {
  const { h, api } = H;
  const FADE_MS = 60 * 1000;
  const NOTE_MS = 30 * 60 * 1000;
  let status = null;
  let shown = null;      // the window on screen
  let noted = 0;         // the stop time already announced
  let faded = 0;         // the stop time already faded for
  let preview = false;   // shown from the settings page, to see how it looks

  const overlay = h('div', { class: 'rest', id: 'rest', hidden: true, role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'rest-greeting' });
  document.body.appendChild(overlay);

  function turnOff() {
    if (preview) {
      return h('div', { class: 'rest-foot' },
        h('button', { class: 'btn btn-gold btn-sm', type: 'button', onclick: () => endPreview() }, 'חזרה להגדרות'));
    }
    const off = h('button', { class: 'rest-off', type: 'button' }, 'המחשב הזה לא שומר שבת? לכבות את מצב השבת');
    const ask = h('div', { class: 'rest-confirm', hidden: true },
      h('span', {}, 'לכבות את מצב השבת ולחזור לנגן?'),
      h('button', { class: 'btn btn-gold btn-sm', type: 'button', onclick: async () => {
        try {
          H.settings = await api.updateSettings({ shabbat_mode: false });
        } catch { /* the screen stays */ }
        await refresh();
      } }, 'כן, לכבות'),
      h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => { ask.hidden = true; off.hidden = false; } }, 'לא'));
    off.addEventListener('click', () => { off.hidden = true; ask.hidden = false; });
    return h('div', { class: 'rest-foot' }, off, ask);
  }

  function render(win) {
    const title = [win.kind !== 'shabbat' ? win.title : '', win.detail].filter(Boolean).join(' · ');
    H.clear(overlay).append(
      h('div', { class: 'rest-inner' },
        h('div', { class: 'rest-candles', 'aria-hidden': 'true' },
          h('span', { class: 'candle' }, h('span', { class: 'flame' })),
          h('span', { class: 'candle' }, h('span', { class: 'flame' }))),
        h('div', { class: 'rest-kicker' }, win.hebrew),
        h('h1', { class: 'rest-greeting', id: 'rest-greeting' }, win.greeting),
        title ? h('div', { class: 'rest-title' }, title) : null,
        h('dl', { class: 'rest-times' },
          h('div', {}, h('dt', {}, 'הדלקת נרות'), h('dd', {}, win.candle_text)),
          h('div', {}, h('dt', {}, win.end_label), h('dd', {}, win.end_text))),
        h('p', { class: 'rest-note' }, `המוזיקה תחזור אחרי ${win.end_label}. הזמנים ל${status ? status.city : ''}, לפי ${win.source_label}.`),
        turnOff()));
  }

  function show(win) {
    if (shown && shown.start_ms === win.start_ms && !overlay.hidden) return;
    shown = win;
    render(win);
    // The Google page lies over the window: it goes away first.
    if (H.currentView && H.currentView() === 'websearch') H.closeWebSearch();
    overlay.hidden = false;
    document.body.classList.add('at-rest');
    H.player.setBlocked(true);
  }

  function hide() {
    if (overlay.hidden) return;
    const was = shown;
    overlay.hidden = true;
    shown = null;
    document.body.classList.remove('at-rest');
    H.player.setBlocked(false);
    // Turned off by hand: no greeting. After the time: "שבוע טוב".
    if (was && Date.now() >= was.end_ms) {
      H.toast(was.days.length && new Date(`${was.days[was.days.length - 1]}T12:00:00`).getDay() === 6 ? 'שבוע טוב!' : 'מועדים לשמחה!', { icon: 'sun' });
    }
  }

  function startPreview(win) {
    if (!win) return;
    preview = true;
    shown = null;
    render(win);
    overlay.hidden = false;
    document.body.classList.add('at-rest');
  }

  function endPreview() {
    preview = false;
    overlay.hidden = true;
    shown = null;
    document.body.classList.remove('at-rest');
    tick();
  }

  function tick() {
    if (preview) return;
    const now = Date.now();
    if (!status || !status.enabled) { hide(); return; }
    const wins = [status.current, status.next].filter(Boolean);
    const active = wins.find((w) => now >= w.stop_ms && now < w.end_ms);
    if (active) {
      if (H.player.isPlaying() && faded !== active.stop_ms) {
        faded = active.stop_ms;
        H.player.fadeOutAndStop(4000).then(() => show(active));
      } else if (!H.player.isPlaying()) {
        show(active);
      }
      return;
    }
    hide();
    const next = wins.find((w) => w.stop_ms > now);
    if (!next) {
      if (wins.length) refresh();   // the window ended: ask for the next one
      return;
    }
    const left = next.stop_ms - now;
    if (left <= NOTE_MS && noted !== next.stop_ms) {
      noted = next.stop_ms;
      const what = next.kind === 'shabbat' ? 'השבת' : next.title;
      H.toast(`המוזיקה תיעצר ב-${next.stop_text}, לקראת ${what} (הדלקת נרות ${next.candle_text}).`, { icon: 'moon' });
    }
    if (left <= FADE_MS && faded !== next.stop_ms && H.player.isPlaying()) {
      faded = next.stop_ms;
      H.player.fadeOutAndStop(left);
    }
  }

  async function refresh() {
    try {
      status = await api.shabbatStatus();
    } catch { /* keep the last answer */ }
    tick();
    return status;
  }

  H.shabbat = { refresh, show, hide, preview: startPreview, endPreview, status: () => status, shown: () => !overlay.hidden };
  refresh();
  setInterval(tick, 5000);
  setInterval(refresh, 20 * 60 * 1000);
})();
