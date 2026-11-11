'use strict';

/*
 * Results: what the request was understood as, the songs it found, and —
 * when the song is not on this computer — the online search, inline.
 */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-results');
  let current = null; // the last response

  async function show(params = {}) {
    H.clear(root).appendChild(h('div', { class: 'results-head' },
      h('div', { class: 'results-kicker' }, icon('loader-circle', 'icon-sm spin'), 'מחפש…')));
    let res;
    try {
      res = params.text !== undefined
        ? await api.ask(params.text)
        : await api.playlist(params.kind, { topic: params.topic, minutes: params.minutes, limit: params.limit });
    } catch (err) {
      H.clear(root).appendChild(H.emptyState('הבקשה לא הצליחה', err.message));
      return;
    }
    current = res;
    render(res, params);
    if (params.autoplay && res.tracks.length) H.player.playList(res.tracks, 0);
  }

  function render(res, params) {
    const total = res.tracks.length;
    const head = h('header', { class: 'results-head' },
      h('div', { class: 'results-kicker' }, params.text !== undefined ? `ביקשת: „${params.text}”` : 'רשימה'),
      h('h1', { class: 'results-title' }, res.understood || 'תוצאות'),
      total ? h('div', { class: 'results-meta num' }, `${H.songs(total)} · ${H.span(res.seconds)}`) : null,
      total ? h('div', { class: 'results-actions' },
        h('button', { class: 'btn btn-primary', type: 'button', onclick: () => H.player.playList(res.tracks, 0, { shuffle: false }) }, icon('play'), 'נגן לפי הסדר'),
        h('button', { class: 'btn btn-outline', type: 'button', onclick: () => H.player.playList(res.tracks, 0, { shuffle: true }) }, icon('shuffle'), 'ערבב'),
        h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => { H.player.enqueue(res.tracks); H.toast(`${H.songs(total)} נוספו לתור`, { icon: 'list-music' }); } }, icon('list-music'), 'הוספה לתור')) : null);

    const parts = [head];
    if (total) {
      parts.push(H.trackList(res.tracks));
    } else if (res.intent && res.intent.action === 'search_song') {
      parts.push(H.emptyState('השיר לא נמצא במחשב', 'מחפש אותו ברשת — אם יימצא, אפשר להוריד אותו והוא יתווסף לספרייה.'));
      parts.push(onlinePanel(res.query || params.text || ''));
    } else {
      parts.push(H.emptyState(res.note || 'לא נמצאו שירים', null,
        h('button', { class: 'btn btn-outline', type: 'button', onclick: () => H.go('home') }, 'חזרה לבית')));
    }
    H.clear(root).append(...parts);
  }

  // ------------------------------------------------------------ online search
  function onlinePanel(query) {
    const list = h('div', { class: 'online-list' });
    const status = h('p', { class: 'muted' }, 'מחפש ביוטיוב…');
    const browserBtn = h('button', { class: 'btn btn-quiet', type: 'button' }, icon('external-link'), 'לפתוח את החיפוש בדפדפן');
    const panel = h('section', { class: 'online', 'aria-label': 'חיפוש ברשת' },
      h('div', { class: 'online-head' }, icon('search'), h('h3', {}, `חיפוש ברשת: ${query}`)),
      status, list, h('div', {}, browserBtn));

    api.onlineSearch(query, 6).then((r) => {
      browserBtn.addEventListener('click', () => api.openExternal(r.search_url));
      if (!r.available) {
        status.textContent = 'רכיב ההורדה (yt-dlp) לא מותקן בגרסה הזו, אז אפשר רק לפתוח את החיפוש בדפדפן.';
        return;
      }
      if (!r.ok || !r.results.length) {
        status.textContent = r.message && /urlopen|network|resolve|getaddrinfo|timed out/i.test(r.message)
          ? 'אין כרגע חיבור לרשת. החיפוש יעבוד כשהמחשב יתחבר.'
          : (r.message || 'לא נמצאו תוצאות.');
        return;
      }
      status.textContent = 'בחרתי את התוצאה הכי מתאימה. לא לזה התכוונת? אפשר לבחור אחרת.';
      let chosen = 0;
      const draw = () => {
        H.clear(list);
        r.results.forEach((item, i) => {
          const row = h('div', { class: `online-item${i === chosen ? ' chosen' : ''}` },
            h('div', { class: 'o-main' },
              h('div', { class: 'o-title' }, item.title || item.id),
              h('div', { class: 'o-sub' }, [item.uploader, item.duration ? H.clock(item.duration) : ''].filter(Boolean).join(' · '))),
            h('div', { class: 'o-actions' },
              h('button', { class: `btn ${i === chosen ? 'btn-primary' : 'btn-outline'} btn-sm`, type: 'button', onclick: () => H.download(item) }, icon('download', 'icon-sm'), 'הורדה לספרייה'),
              h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.openExternal(item.url) }, 'ביוטיוב'),
              i === chosen ? null : h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => { chosen = i; draw(); } }, 'זה השיר')));
          list.appendChild(row);
        });
      };
      draw();
    }).catch((err) => { status.textContent = `החיפוש נכשל: ${err.message}`; });
    return panel;
  }

  H.views = H.views || {};
  H.views.results = { show, current: () => current };
})();
