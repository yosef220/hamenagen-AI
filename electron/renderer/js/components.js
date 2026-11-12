'use strict';

/* Building blocks shared by the views: covers, track rows, tiles, the drawer. */
(function () {
  const { h, icon, api } = H;

  // ------------------------------------------------------------ covers
  /** The song's picture (cover://<key>, made small by the main process),
   * over its first letter, which shows while it loads or when there is none. */
  H.cover = function cover(track, size = 'xs') {
    const title = H.trackTitle(track);
    const el = h('div', { class: `cover cover-${size}`, 'aria-hidden': 'true', 'data-tint': H.tint(track.topic) }, H.letter(title));
    if (track.cover) setCoverArt(el, track.cover);
    return el;
  };

  function setCoverArt(el, key) {
    const old = el.querySelector('img');
    if (old) old.remove();
    const img = h('img', { src: `cover://${key}/`, alt: '', loading: 'lazy', decoding: 'async', draggable: 'false' });
    img.addEventListener('error', () => { img.remove(); el.classList.remove('has-art'); });
    el.classList.add('has-art');
    el.appendChild(img);
  }

  /** Show a song's new cover wherever the song is on screen. */
  H.refreshCover = function refreshCover(id, key) {
    for (const el of H.$$(`[data-id="${CSS.escape(id)}"] .cover`)) setCoverArt(el, key);
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
    // No artist or album in the file: its folder usually names them.
    const sub = [track.artist, track.album].filter(Boolean).join(' · ') || track.folder || '';
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
        h('div', { class: 'track-topic', 'data-tint': H.tint(track.topic), title: topicWhy(track) }, topicLabel(track)),
        h('div', { class: 'track-dur' }, track.duration ? H.clock(track.duration) : ''),
        heartButton(track),
        h('button', {
          class: 'icon-btn more',
          type: 'button',
          'aria-label': `עוד פעולות על ${H.trackTitle(track)}`,
          'aria-haspopup': 'menu',
          onclick: (e) => { e.stopPropagation(); H.openTrackMenu(track, e.currentTarget); },
        }, icon('ellipsis')));
    row.addEventListener('dblclick', play);
    if (opts.compact) row.addEventListener('click', play);
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') play();
      if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) {
        e.preventDefault();
        H.openTrackMenu(track, row);
      }
    });
    row.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      H.openTrackMenu(track, { x: e.clientX, y: e.clientY });
    });
    return row;
  }

  /** "Why this topic", in the listener's words, for the tooltip and the menu. */
  function topicWhy(track) {
    if (!track.topic) return 'עוד אין נושא לשיר הזה';
    const label = (H.topicLabels && H.topicLabels[track.topic]) || track.topic;
    return track.topic_note ? `${label} — ${track.topic_note}` : label;
  }
  H.topicWhy = topicWhy;

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

  // ------------------------------------------------------------ the song menu
  /*
   * One menu for every song row: why it has its topic, choosing another
   * topic, marking it vocal (or not), queueing it and finding the file.
   * Corrections go to the core, which keeps them across scans and lets the
   * rest of the album follow.
   */
  const songMenu = h('div', { class: 'menu track-menu', id: 'track-menu', role: 'menu', hidden: true, 'aria-label': 'פעולות על השיר' });
  document.body.appendChild(songMenu);
  let menuTrack = null;
  let menuReturn = null;
  let menuOpenedAt = 0;
  let menuViewport = '';

  function closeTrackMenu() {
    if (songMenu.hidden) return;
    // Give focus back only if it was inside the menu (keyboard use), and
    // without scrolling: the page may have moved since the menu opened.
    const hadFocus = songMenu.contains(document.activeElement);
    songMenu.hidden = true;
    menuTrack = null;
    if (hadFocus && menuReturn && menuReturn.focus && document.contains(menuReturn)) menuReturn.focus({ preventScroll: true });
    menuReturn = null;
  }
  H.closeTrackMenu = closeTrackMenu;

  /** Apply what the core returned to every copy of the song on screen. */
  function applyTrack(track, fresh) {
    if (!fresh) return;
    for (const key of ['topic', 'topic_source', 'topic_note', 'tags', 'vocal', 'topic_chosen']) track[key] = fresh[key];
    for (const q of [H.player.queue, H.player.original]) {
      for (const t of q) if (t.id === track.id) Object.assign(t, { topic: fresh.topic, tags: fresh.tags, topic_note: fresh.topic_note });
    }
    for (const row of H.$$(`.track[data-id="${CSS.escape(track.id)}"]`)) {
      const cell = row.querySelector('.track-topic');
      if (cell) {
        cell.textContent = topicLabel(track);
        cell.dataset.tint = H.tint(track.topic);
        cell.title = topicWhy(track);
      }
      const cover = row.querySelector('.cover');
      if (cover) cover.dataset.tint = H.tint(track.topic);
    }
    api.emit('track-changed', { id: track.id, track });
  }

  async function chooseTopic(track, topic) {
    closeTrackMenu();
    try {
      const res = await api.setTrackTopic(track.id, topic);
      applyTrack(track, res.track);
      const label = topic === null ? 'אוטומטי' : topic === '' ? 'בלי נושא' : ((H.topicLabels && H.topicLabels[topic]) || topic);
      const more = res.propagated ? ` · ${H.songs(res.propagated)} מאותו אלבום או תיקייה התעדכנו` : '';
      H.toast(`„${H.trackTitle(track)}”: ${label}${more}`, { icon: 'tag' });
    } catch (err) {
      H.toast(`לא הצלחתי לשנות: ${err.message}`, { kind: 'bad' });
    }
  }

  async function chooseVocal(track, value) {
    closeTrackMenu();
    try {
      const res = await api.setTrackVocal(track.id, value);
      applyTrack(track, res.track);
      H.toast(value === true ? `„${H.trackTitle(track)}” סומן כווקאלי` : value === false
        ? `„${H.trackTitle(track)}” סומן כשיר עם כלי נגינה` : 'הזיהוי חזר להיות אוטומטי', { icon: 'mic-vocal' });
    } catch (err) {
      H.toast(`לא הצלחתי לשמור: ${err.message}`, { kind: 'bad' });
    }
  }

  function item(iconName, label, onclick, attrs = {}) {
    return h('button', { type: 'button', role: 'menuitem', class: 'menu-item', onclick, ...attrs },
      iconName ? icon(iconName, 'icon-sm') : null, h('span', {}, label));
  }

  function renderTrackMenu(track) {
    const topics = (H.cachedTopics || []).length ? H.cachedTopics : Object.entries(H.topicLabels || {}).map(([key, label]) => ({ key, label }));
    const vocalState = track.vocal === 'yes' ? 'yes' : track.vocal === 'no' ? 'no' : 'auto';
    const heard = track.vocal === 'vocal' ? 'המנגן שמע בשיר שירה בלי כלי נגינה.'
      : track.vocal === 'maybe' ? 'נשמע כמו שירה בלי כלים, אבל לא בטוח.' : '';
    const topicButtons = topics.map((t) => h('button', {
      type: 'button',
      role: 'menuitemradio',
      class: 'chip-choice',
      'data-tint': H.tint(t.key),
      'aria-checked': track.topic === t.key ? 'true' : 'false',
      onclick: () => chooseTopic(track, t.key),
    }, t.label));
    H.clear(songMenu).append(
      h('div', { class: 'menu-head' },
        h('div', { class: 'menu-song' }, H.trackTitle(track)),
        h('div', { class: 'menu-why' }, icon('info', 'icon-sm'), h('span', {}, topicWhy(track)))),
      h('div', { class: 'menu-group' },
        item('list-start', 'לנגן אחרי השיר הזה', () => { closeTrackMenu(); H.player.playNext(track); H.toast('יתנגן אחרי השיר הזה', { icon: 'list-start' }); }),
        item('list-plus', 'להוסיף לסוף התור', () => { closeTrackMenu(); H.player.enqueue([track]); H.toast('נוסף לתור', { icon: 'list-plus' }); }),
        track.path ? item('folder-open', 'להציג בתיקייה', () => { closeTrackMenu(); api.showInFolder(track.path); }) : null,
        item('image', 'פרטים ותמונה מהרשת…', () => { closeTrackMenu(); H.openDetails(track); })),
      h('div', { class: 'menu-group' },
        h('div', { class: 'menu-label' }, 'הנושא של השיר'),
        h('div', { class: 'chip-grid', role: 'group', 'aria-label': 'נושא' }, topicButtons),
        h('div', { class: 'menu-row' },
          h('button', { type: 'button', role: 'menuitemradio', class: 'chip-choice', 'aria-checked': !track.topic && track.topic_chosen ? 'true' : 'false', onclick: () => chooseTopic(track, '') }, 'בלי נושא'),
          track.topic_chosen ? h('button', { type: 'button', role: 'menuitem', class: 'chip-choice quiet', onclick: () => chooseTopic(track, null) }, icon('undo-2', 'icon-sm'), 'לחזור לנושא האוטומטי') : null)),
      h('div', { class: 'menu-group' },
        h('div', { class: 'menu-label' }, 'שירה בלי כלי נגינה'),
        h('div', { class: 'segmented segmented-sm', role: 'group', 'aria-label': 'ווקאלי' },
          [['yes', 'ווקאלי', true], ['no', 'יש כלים', false], ['auto', 'אוטומטי', null]].map(([key, label, value]) =>
            h('button', { type: 'button', role: 'menuitemradio', 'aria-pressed': vocalState === key ? 'true' : 'false', 'aria-checked': vocalState === key ? 'true' : 'false', onclick: () => chooseVocal(track, value) }, label))),
        heard ? h('p', { class: 'menu-note' }, icon('ear', 'icon-sm'), heard) : null),
    );
  }

  // ------------------------------------------------------------ details from the web
  const detailsDialog = h('dialog', { class: 'dialog', 'aria-labelledby': 'details-title' });
  document.body.appendChild(detailsDialog);
  detailsDialog.addEventListener('click', (e) => { if (e.target === detailsDialog) detailsDialog.close(); });

  function showTrackText(track) {
    for (const row of H.$$(`.track[data-id="${CSS.escape(track.id)}"]`)) {
      const title = row.querySelector('.track-title');
      if (title) { title.textContent = H.trackTitle(track); title.title = H.trackTitle(track); }
      const sub = row.querySelector('.track-sub');
      const text = [track.artist, track.album].filter(Boolean).join(' · ');
      if (sub && text) sub.textContent = text;
    }
  }

  /** Look the song up on the web and let the listener pick the right one.
   * The choice is kept by the app; the file itself is never changed. */
  H.openDetails = async function openDetails(track) {
    const body = h('div', { class: 'dialog-body' },
      h('p', { class: 'muted dialog-wait' }, icon('loader-circle', 'icon-sm spin'), 'מחפש את השיר ברשת…'));
    H.clear(detailsDialog).append(
      h('header', { class: 'dialog-head' },
        h('div', { class: 'dialog-heading' },
          h('h2', { id: 'details-title' }, 'פרטים ותמונה מהרשת'),
          h('p', { class: 'muted' }, [H.trackTitle(track), track.artist].filter(Boolean).join(' · '))),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'סגירה', onclick: () => detailsDialog.close() }, icon('x'))),
      body,
      h('footer', { class: 'dialog-foot' }, icon('info', 'icon-sm'),
        h('span', {}, 'נשלחים רק שם השיר, הזמר והאורך, ל-Apple (iTunes). מה שנבחר נשמר במנגן — הקובץ עצמו לא משתנה.')));
    if (!detailsDialog.open) detailsDialog.showModal();
    let res;
    try {
      res = await api.lookupDetails(track.id);
    } catch (err) {
      body.replaceChildren(H.emptyState('החיפוש נכשל', err.message));
      return;
    }
    if (!res.candidates.length) {
      body.replaceChildren(H.emptyState(res.message || 'לא נמצאו פרטים לשיר הזה',
        res.error === 'blocked' ? 'הרשת במחשב הזה חוסמת את השירות. אפשר להשאיר את השיר כמו שהוא.'
          : 'השירות לא מכיר את השיר בשם הזה. אפשר לנסות שוב אחרי תיקון שם הקובץ.'));
      return;
    }
    const list = h('div', { class: 'cand-list', role: 'list' });
    const apply = async (c, btn) => {
      for (const b of H.$$('button', list)) b.disabled = true;
      btn.replaceChildren(icon('loader-circle', 'icon-sm spin'), 'שומר…');
      try {
        const out = await api.applyDetails(track.id, c, true);
        detailsDialog.close();
        if (out.track) {
          Object.assign(track, out.track);
          applyTrack(track, out.track);
          showTrackText(track);
        }
        if (out.cover_key) for (const id of [track.id, ...(out.covered_ids || [])]) H.refreshCover(id, out.cover_key);
        const more = out.propagated ? ` · התמונה נוספה גם ל-${H.songs(out.propagated)} באותה תיקייה` : '';
        H.toast(out.message || `„${H.trackTitle(track)}” עודכן${more}`, { icon: 'image' });
        api.emit('library-changed', {});
      } catch (err) {
        for (const b of H.$$('button', list)) b.disabled = false;
        btn.replaceChildren(icon('check', 'icon-sm'), 'זה השיר');
        H.toast(`לא הצלחתי לשמור: ${err.message}`, { kind: 'bad' });
      }
    };
    for (const c of res.candidates) {
      const pick = h('button', { class: 'btn btn-primary btn-sm', type: 'button' }, icon('check', 'icon-sm'), 'זה השיר');
      pick.addEventListener('click', () => apply(c, pick));
      list.appendChild(h('div', { class: 'cand', role: 'listitem' },
        h('div', { class: 'cand-art' }, c.cover_url
          ? h('img', { src: c.cover_url.replace('600x600bb', '200x200bb'), alt: '', loading: 'lazy' })
          : icon('image')),
        h('div', { class: 'cand-main' },
          h('div', { class: 'cand-title' }, c.title),
          h('div', { class: 'cand-sub' }, [c.artist, c.album].filter(Boolean).join(' · ')),
          h('div', { class: 'cand-sub num' }, [c.year, c.duration ? H.clock(c.duration) : ''].filter(Boolean).join(' · '))),
        h('div', { class: 'cand-actions' }, pick,
          c.url ? h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.openExternal(c.url) }, 'לפתוח') : null)));
    }
    body.replaceChildren(
      h('p', { class: 'muted' }, 'בחרו את השיר הנכון, או סגרו אם אף אחד מהם לא מתאים. התמונה תשמש גם לשירים באותה תיקייה שאין להם תמונה.'),
      list);
  };

  /** Open the song menu next to a button/row, or at a point {x, y}. */
  H.openTrackMenu = function openTrackMenu(track, where) {
    if (!songMenu.hidden && menuTrack && menuTrack.id === track.id && !(where && 'x' in where)) { closeTrackMenu(); return; }
    menuTrack = track;
    menuReturn = where instanceof Element ? where : document.activeElement;
    renderTrackMenu(track);
    songMenu.hidden = false;
    menuOpenedAt = performance.now();
    menuViewport = `${window.innerWidth}x${window.innerHeight}`;
    const w = songMenu.offsetWidth;
    const hgt = songMenu.offsetHeight;
    let x;
    let y;
    if (where instanceof Element) {
      const r = where.getBoundingClientRect();
      x = r.right - w;            // RTL: the menu's right edge under the button's
      y = r.bottom + 6;
      if (y + hgt > window.innerHeight - 8) y = Math.max(8, r.top - hgt - 6);
    } else {
      x = where.x - w;
      y = where.y;
      if (y + hgt > window.innerHeight - 8) y = Math.max(8, window.innerHeight - hgt - 8);
    }
    x = Math.min(Math.max(8, x), window.innerWidth - w - 8);
    songMenu.style.setProperty('left', `${x}px`);
    songMenu.style.setProperty('top', `${y}px`);
    const first = songMenu.querySelector('button');
    if (first) first.focus({ preventScroll: true });
  };

  songMenu.addEventListener('keydown', (e) => {
    const items = H.$$('button', songMenu);
    const i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length];
      if (next) next.focus();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closeTrackMenu();
    }
  });
  document.addEventListener('mousedown', (e) => { if (!songMenu.hidden && !songMenu.contains(e.target)) closeTrackMenu(); });
  window.addEventListener('blur', closeTrackMenu);
  window.addEventListener('resize', () => {
    if (`${window.innerWidth}x${window.innerHeight}` !== menuViewport) closeTrackMenu();
  });
  // Scrolling the page closes the menu; scrolling inside the menu does not,
  // nor the scroll that brought the row into view (scroll events arrive late).
  document.addEventListener('scroll', (e) => {
    if (!songMenu.contains(e.target) && performance.now() - menuOpenedAt > 250) closeTrackMenu();
  }, true);

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
