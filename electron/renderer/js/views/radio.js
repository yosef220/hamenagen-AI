'use strict';

/* Radio: Kol Chai Music's live channels — the main broadcast first — then
   more stations, and stations the listener adds by address (1.5). */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-radio');
  // Kol Chai's categories, in the order the page shows them.
  const GROUPS = [[2, 'אווירה ומועדים'], [1, 'סגנונות'], [3, 'אמנים']];
  const groupName = (st) => st.group || (GROUPS.find(([c]) => c === st.category) || [0, 'מיוחדים'])[1];
  const MORE = ['תחנות נוספות', 'דיבור וחדשות', 'התחנות שלי'];
  let stations = [];
  let info = null;

  function stationCover(st, cls) {
    const c = h('div', { class: `cover cover-radio ${cls || ''}`, 'aria-hidden': 'true' }, H.letter(st.title));
    if (st.image_url) {
      const img = h('img', { src: st.image_url, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' });
      img.addEventListener('error', () => img.remove());
      c.appendChild(img);
    }
    return c;
  }

  function isOn(st) {
    const P = H.player;
    return P.mode === 'radio' && P.station && P.station.id === st.id;
  }

  function stationCard(st) {
    const on = isOn(st);
    return h('button', {
      class: `station${on ? ' on' : ''}`,
      type: 'button',
      'data-station': st.id,
      'aria-label': `${st.title}${on ? ', מתנגן עכשיו' : ''}`,
      onclick: () => (isOn(st) ? H.player.toggle() : H.player.playStation(st)),
    },
    stationCover(st),
    h('div', { class: 'station-main', style: { 'min-width': '0' } },
      h('div', { class: 'station-title' }, st.title),
      h('div', { class: 'station-sub' }, st.now_playing || st.description || ''),
      on ? h('span', { class: 'on-air' }, h('span', { class: 'live-dot' }), 'בשידור עכשיו') : null),
    h('span', { class: 'play-mark' }, icon(on && H.player.isPlaying() ? 'pause' : 'play')),
    st.custom ? h('span', { class: 'icon-btn station-remove', role: 'button', tabindex: '0', title: 'להסיר את התחנה',
      'aria-label': `להסיר את ${st.title}`, onclick: (e) => { e.stopPropagation(); removeStation(st); } }, icon('x', 'icon-sm')) : null);
  }

  async function saveStations(list) {
    try {
      H.settings = await api.updateSettings({ custom_stations: list });
      await load(false);
      return true;
    } catch (err) {
      H.toast(`לא הצלחתי לשמור: ${err.message}`, { kind: 'bad' });
      return false;
    }
  }

  function removeStation(st) {
    const list = (H.settings.custom_stations || []).filter((s) => s.url !== st.url);
    saveStations(list).then((ok) => ok && H.toast(`„${st.title}” הוסרה`, { icon: 'radio' }));
  }

  // A station by its address (an https stream, as a station's site gives it).
  function addForm() {
    const title = h('input', { type: 'text', placeholder: 'שם התחנה', 'aria-label': 'שם התחנה', maxlength: '80' });
    const url = h('input', { type: 'url', placeholder: 'https://…', 'aria-label': 'כתובת השידור', dir: 'ltr' });
    const note = h('p', { class: 'set-help' }, 'כתובת של שידור חי (מתחילה ב-https). אפשר למצוא אותה באתר של התחנה, בדרך כלל תחת „האזנה” או „שידור חי”.');
    const form = h('form', { class: 'station-add', onsubmit: async (e) => {
      e.preventDefault();
      const u = url.value.trim();
      if (!/^https:\/\//i.test(u)) { note.textContent = 'הכתובת צריכה להתחיל ב-https://'; return; }
      const list = [...(H.settings.custom_stations || []), { title: title.value.trim(), url: u }];
      if (await saveStations(list)) H.toast('התחנה נוספה', { icon: 'radio' });
    } },
    h('label', { class: 'field' }, icon('radio'), title),
    h('label', { class: 'field' }, icon('link'), url),
    h('button', { class: 'btn btn-outline', type: 'submit' }, icon('plus', 'icon-sm'), 'להוסיף'));
    return h('section', { class: 'radio-group', 'aria-label': 'הוספת תחנה' }, h('h3', {}, 'הוספת תחנה'), form, note);
  }

  function draw() {
    if (!info) return;
    const main = stations.find((s) => s.id === 1) || stations[0];
    const rest = stations.filter((s) => s !== main);
    const parts = [
      h('header', { class: 'page-head' },
        h('h1', {}, 'רדיו'),
        h('div', { class: 'page-meta status-line' }, info.online
          ? [icon('signal'), `קול חי מיוזיק · ${H.channels(info.kcm_count || stations.length)} · ועוד ${H.n(stations.length - (info.kcm_count || stations.length))} תחנות`]
          : [icon('wifi-off'), `אין חיבור לרשת — רשימת ערוצים שמורה (${H.channels(stations.length)}). השידור יעבוד כשהמחשב יתחבר.`]),
        h('div', { class: 'page-actions' },
          h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => load(true) }, icon('refresh-cw'), 'רענון'))),
    ];
    if (main) {
      const on = isOn(main);
      parts.push(h('section', { class: 'radio-hero', 'aria-label': main.title },
        stationCover(main),
        h('div', {},
          h('div', { class: 'muted' }, 'השידור המרכזי · 102.5FM'),
          h('h2', {}, main.title),
          h('div', { class: 'muted' }, main.now_playing || main.description || '')),
        h('button', { class: 'btn btn-primary', type: 'button', onclick: () => (isOn(main) ? H.player.toggle() : H.player.playStation(main)) },
          icon(on && H.player.isPlaying() ? 'pause' : 'play'), on && H.player.isPlaying() ? 'השהה' : 'האזנה')));
    }
    const groups = new Map();
    for (const st of rest) {
      const g = groupName(st);
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(st);
    }
    for (const name of [...GROUPS.map(([, n]) => n), 'מיוחדים', ...MORE]) {
      const list = groups.get(name);
      if (!list || !list.length) continue;
      parts.push(h('section', { class: 'radio-group', 'aria-label': name }, h('h3', {}, name), h('div', { class: 'stations' }, list.map(stationCard))));
    }
    parts.push(addForm());
    H.clear(root).append(...parts);
  }

  async function load(refresh) {
    if (!info) {
      H.clear(root).appendChild(h('div', { class: 'status-line' }, icon('loader-circle', 'spin'), 'טוען את ערוצי קול חי…'));
    }
    try {
      info = await api.radioList(refresh);
      stations = info.stations || [];
      draw();
    } catch (err) {
      H.clear(root).appendChild(H.emptyState('הרדיו לא נטען', err.message));
    }
  }

  H.player.on((what) => {
    if (!root.hidden && ['station', 'play', 'pause', 'stop', 'track'].includes(what)) draw();
  });

  H.views = H.views || {};
  H.views.radio = { show: () => load(!info || !info.online) };
})();
