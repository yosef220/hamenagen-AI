'use strict';

/* Building blocks shared by the views: covers, track rows, tiles, the drawer. */
(function () {
  const { h, icon, api } = H;

  // ------------------------------------------------------------ covers
  H.cover = function cover(track, size = 'xs') {
    const title = H.trackTitle(track);
    return h('div', { class: `cover cover-${size}`, 'aria-hidden': 'true', 'data-tint': H.tint(track.topic) }, H.letter(title));
  };

  // ------------------------------------------------------------ favorites
  /** Flip a song's heart everywhere it is shown, then tell the core. */
  H.toggleFavorite = async function toggleFavorite(track) {
    const on = !track.favorite;
    const apply = (value) => {
      track.favorite = value;
      for (const q of [H.player.queue, H.player.original]) {
        for (const t of q) if (t.id === track.id) t.favorite = value;
      }
      for (const btn of H.$$(`[data-fav-id="${CSS.escape(track.id)}"]`)) {
        btn.setAttribute('aria-pressed', value ? 'true' : 'false');
        btn.setAttribute('aria-label', value ? 'הסרה מהלב' : 'סימון בלב');
      }
    };
    apply(on);
    try {
      await api.setFavorite(track.id, on);
      api.emit('favorites-changed', { id: track.id, on });
      if (on) H.toast(`"${H.trackTitle(track)}" נשמר בשירים שאהבת`, { icon: 'heart' });
    } catch (err) {
      apply(!on);
      H.toast(`לא הצלחתי לשמור: ${err.message}`, { kind: 'bad' });
    }
  };

  function heartButton(track) {
    return h(
      'button',
      {
        class: 'icon-btn heart',
        type: 'button',
        'data-fav-id': track.id,
        'aria-pressed': track.favorite ? 'true' : 'false',
        'aria-label': track.favorite ? 'הסרה מהלב' : 'סימון בלב',
        onclick: (e) => { e.stopPropagation(); H.toggleFavorite(track); },
      },
      icon('heart'),
    );
  }

  // ------------------------------------------------------------ track rows
  /**
   * A list of songs. Double-click (or Enter) plays from that song; the
   * number turns into a play button on hover. `opts.compact` drops the topic
   * and number columns (home page lists).
   */
  H.trackList = function trackList(tracks, opts = {}) {
    const list = h('div', { class: `tracks${opts.compact ? ' tracks-compact' : ''}`, role: 'list' });
    H.appendTracks(list, tracks, 0, opts);
    return list;
  };

  H.appendTracks = function appendTracks(list, tracks, offset, opts = {}) {
    const source = opts.source || tracks;
    tracks.forEach((track, i) => list.appendChild(trackRow(track, offset + i, source, opts)));
    markActive(list);
  };

  function trackRow(track, i, source, opts) {
    const play = () => {
      if (opts.onPlay) opts.onPlay(i);
      else H.player.playList(source, i);
    };
    const sub = [track.artist, track.album].filter(Boolean).join(' · ') || (track.title ? track.filename : '');
    const main = h(
      'div',
      { class: 'track-main' },
      h('div', { class: 'track-title', title: H.trackTitle(track) }, H.trackTitle(track)),
      sub ? h('div', { class: 'track-sub' }, sub) : null,
    );
    const row = opts.compact
      ? h('div', { class: 'track', role: 'listitem', tabindex: '0', 'data-id': track.id },
        H.cover(track), main,
        h('div', { class: 'track-dur' }, track.duration ? H.clock(track.duration) : ''))
      : h('div', { class: 'track', role: 'listitem', tabindex: '0', 'data-id': track.id },
        h('div', { class: 'track-idx' },
          h('span', { class: 'idx-n' }, String(i + 1)),
          h('button', { class: 'icon-btn play-hint', type: 'button', 'aria-label': `נגן את ${H.trackTitle(track)}`, onclick: (e) => { e.stopPropagation(); play(); } }, icon('play', 'icon-sm'))),
        H.cover(track), main,
        h('div', { class: 'track-topic', 'data-tint': H.tint(track.topic) }, topicLabel(track)),
        h('div', { class: 'track-dur' }, track.duration ? H.clock(track.duration) : ''),
        heartButton(track));
    row.addEventListener('dblclick', play);
    if (opts.compact) row.addEventListener('click', play);
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') play();
    });
    return row;
  }

  function topicLabel(track) {
    if (!track.topic) return '';
    const label = (H.topicLabels && H.topicLabels[track.topic]) || track.topic;
    return track.tags && track.tags.length ? `${label} · ${track.tags.join(' · ')}` : label;
  }

  /** Highlight the row of the song that is playing, in every list on screen. */
  function markActive(root = document) {
    const cur = H.player && H.player.current();
    for (const row of H.$$('.track[data-id]', root)) {
      const on = !!cur && row.dataset.id === cur.id;
      row.classList.toggle('active', on);
      const idx = row.querySelector('.idx-n');
      if (idx) {
        const playing = on && H.player.isPlaying();
        if (playing && !idx.querySelector('svg')) { H.clear(idx).appendChild(icon('audio-lines', 'icon-sm')); }
        if (!playing && idx.querySelector('svg')) idx.textContent = String(Array.from(row.parentNode.children).indexOf(row) + 1);
      }
    }
  }
  H.markActive = markActive;

  // ------------------------------------------------------------ topic tiles
  H.topicTile = function topicTile(topic, opts = {}) {
    const tile = h(
      'button',
      {
        class: `tile${topic.count ? '' : ' empty'}`,
        type: 'button',
        'data-tint': H.tint(topic.key),
        'aria-label': `${topic.label}, ${H.songs(topic.count || 0)}`,
        onclick: () => H.openTopic(topic.key),
      },
      h('span', { class: 'tile-letter', 'aria-hidden': 'true' }, H.letter(topic.key)),
      h('span', { class: 'tile-label' }, topic.label),
      opts.phrase ? h('span', { class: 'tile-phrase' }, topic.phrase) : null,
      h('span', { class: 'tile-count num' }, topic.count ? H.songs(topic.count) : 'אין עדיין שירים'),
    );
    return tile;
  };

  H.openTopic = (key) => H.go('results', { kind: 'play_topic', topic: key });

  H.emptyState = function emptyState(title, text, ...actions) {
    return h('div', { class: 'empty-state' }, h('h3', {}, title), text ? h('p', {}, text) : null,
      actions.length ? h('div', { class: 'results-actions' }, actions) : null);
  };

  // ------------------------------------------------------------ drawer
  const drawer = H.$('#drawer');
  const body = H.$('#drawer-body');
  let tab = 'queue';
  let lyricsFor = null;

  H.openDrawer = function openDrawer(which) {
    if (!drawer.hidden && tab === which) { closeDrawer(); return; }
    tab = which;
    drawer.hidden = false;
    for (const t of H.$$('.tab', drawer)) t.setAttribute('aria-selected', t.dataset.tab === tab ? 'true' : 'false');
    H.$('#btn-queue').setAttribute('aria-pressed', tab === 'queue' ? 'true' : 'false');
    H.$('#btn-lyrics').setAttribute('aria-pressed', tab === 'lyrics' ? 'true' : 'false');
    renderDrawer();
  };

  function closeDrawer() {
    drawer.hidden = true;
    H.$('#btn-queue').setAttribute('aria-pressed', 'false');
    H.$('#btn-lyrics').setAttribute('aria-pressed', 'false');
  }
  H.closeDrawer = closeDrawer;

  function renderDrawer() {
    if (drawer.hidden) return;
    H.clear(body);
    const P = H.player;
    if (tab === 'queue') {
      if (P.mode === 'radio') {
        body.appendChild(h('p', { class: 'queue-note' }, `מתנגן עכשיו שידור חי: ${P.station.title}. התור חוזר כשמנגנים שירים מהמחשב.`));
        return;
      }
      if (!P.queue.length) {
        body.appendChild(h('p', { class: 'queue-note' }, 'התור ריק. בקשה, נושא או שיר מהספרייה ימלאו אותו.'));
        return;
      }
      const left = P.queue.slice(P.index + 1).reduce((s, t) => s + (t.duration || 240), 0);
      body.appendChild(h('p', { class: 'queue-note' },
        `${H.songs(P.queue.length)} · עוד ${H.span(left)} אחרי השיר הזה${P.shuffle ? ' · בערבוב' : ''}`));
      const list = h('div', { class: 'tracks tracks-compact', role: 'list' });
      P.queue.forEach((t, i) => {
        const row = h('div', { class: `track${i === P.index ? ' active' : ''}`, role: 'listitem', tabindex: '0', 'data-id': t.id },
          H.cover(t),
          h('div', { class: 'track-main' },
            h('div', { class: 'track-title' }, H.trackTitle(t)),
            t.artist ? h('div', { class: 'track-sub' }, t.artist) : null),
          i === P.index
            ? h('div', { class: 'track-dur' }, t.duration ? H.clock(t.duration) : '')
            : h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'הסרה מהתור', onclick: (e) => { e.stopPropagation(); P.removeAt(i); } }, icon('x', 'icon-sm')));
        row.addEventListener('click', () => P.jump(i));
        list.appendChild(row);
      });
      body.appendChild(list);
      const active = list.querySelector('.active');
      if (active) active.scrollIntoView({ block: 'nearest' });
    } else {
      const cur = P.current();
      if (!cur) {
        body.appendChild(h('p', { class: 'queue-note' }, 'המילים מופיעות כאן כשמתנגן שיר שיש לו קובץ מילים (‎.lrc או ‎.txt באותו שם, באותה תיקייה).'));
        return;
      }
      const box = h('div', { class: 'lyrics' }, '…');
      body.appendChild(h('p', { class: 'queue-note' }, H.trackTitle(cur)));
      body.appendChild(box);
      lyricsFor = cur.id;
      api.lyrics(cur.id).then((res) => {
        if (lyricsFor !== cur.id) return;
        box.textContent = res.lyrics || 'לשיר הזה אין קובץ מילים. אפשר להניח לידו קובץ ‎.lrc או ‎.txt באותו שם.';
        if (!res.lyrics) box.classList.add('muted');
      }).catch(() => { box.textContent = ''; });
    }
  }

  for (const t of H.$$('.tab', drawer)) t.addEventListener('click', () => H.openDrawer(t.dataset.tab));
  H.$('#drawer-close').addEventListener('click', closeDrawer);
  H.$('#btn-queue').addEventListener('click', () => H.openDrawer('queue'));
  H.$('#btn-lyrics').addEventListener('click', () => H.openDrawer('lyrics'));

  // ------------------------------------------------------------ sleep menu
  const menu = H.$('#sleep-menu');
  const sleepBtn = H.$('#btn-sleep');
  function closeMenu() { menu.hidden = true; sleepBtn.setAttribute('aria-expanded', 'false'); }
  sleepBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!menu.hidden) { closeMenu(); return; }
    const r = sleepBtn.getBoundingClientRect();
    menu.hidden = false;
    menu.style.setProperty('left', `${Math.max(8, r.left)}px`);
    menu.style.setProperty('bottom', `${window.innerHeight - r.top + 8}px`);
    sleepBtn.setAttribute('aria-expanded', 'true');
    const sleep = H.player.sleep;
    const current = !sleep ? 'off' : sleep.endOfTrack ? 'track' : String(sleep.minutes);
    for (const b of H.$$('button', menu)) b.setAttribute('aria-checked', b.dataset.sleep === current ? 'true' : 'false');
    const first = menu.querySelector('button');
    if (first) first.focus();
  });
  for (const b of H.$$('button', menu)) {
    b.setAttribute('role', 'menuitemradio');
    b.addEventListener('click', () => {
      H.player.setSleep(b.dataset.sleep);
      closeMenu();
      if (b.dataset.sleep !== 'off') {
        H.toast(b.dataset.sleep === 'track' ? 'הנגינה תיעצר בסוף השיר' : `הנגינה תיעצר ${b.textContent}`, { icon: 'moon' });
      }
    });
  }
  document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeMenu(); } });

  H.player.on((what) => {
    markActive();
    if (['track', 'queue', 'station', 'stop', 'mode'].includes(what)) renderDrawer();
  });
})();
