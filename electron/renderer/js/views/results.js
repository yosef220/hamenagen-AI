'use strict';

/*
 * Results: what the request was understood as, the songs it found, and —
 * when the song is not on this computer — the online search, inline.
 */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-results');
  let current = null; // the last response
  let lastParams = {};

  async function show(params = {}) {
    lastParams = params;
    if (params.link) {
      const holder = h('div', { class: 'link-result' });
      H.clear(root).append(
        h('header', { class: 'results-head' },
          h('div', { class: 'results-kicker' }, 'מהחיפוש בגוגל'),
          h('h1', { class: 'results-title' }, 'קישור מיוטיוב')),
        h('section', { class: 'online' }, holder));
      openLink(params.link, holder);
      return;
    }
    H.clear(root).appendChild(h('div', { class: 'results-head' },
      h('div', { class: 'results-kicker' }, icon('loader-circle', 'icon-sm spin'), 'מחפש…')));
    let res;
    try {
      res = params.text !== undefined
        ? await api.ask(params.text, params.spoken)
        : await api.playlist(params.kind, { topic: params.topic, minutes: params.minutes, limit: params.limit });
    } catch (err) {
      H.clear(root).appendChild(H.emptyState('הבקשה לא הצליחה', err.message));
      return;
    }
    current = res;
    render(res, params);
    if (params.autoplay && res.tracks.length) H.player.playList(res.tracks, 0, playOptions(res));
  }

  /** A set plays in its order, with a soft crossfade. */
  function playOptions(res, extra = {}) {
    return res.set ? { shuffle: false, crossfade: res.set.crossfade, ...extra } : extra;
  }

  function render(res, params) {
    const total = res.tracks.length;
    const head = h('header', { class: 'results-head' },
      h('div', { class: 'results-kicker' }, params.text !== undefined ? `ביקשת: „${params.text}”` : 'רשימה'),
      h('h1', { class: 'results-title' }, res.understood || 'תוצאות'),
      total ? h('div', { class: 'results-meta num' }, `${H.songs(total)} · ${H.span(res.seconds)}${
        res.intent && res.intent.minutes && res.seconds < res.intent.minutes * 60 * 0.9 ? ' — כל מה שיש במאגר' : ''}`) : null,
      total ? h('div', { class: 'results-actions' },
        h('button', { class: 'btn btn-primary', type: 'button', onclick: () => H.player.playList(res.tracks, 0, playOptions(res, { shuffle: false })) }, icon('play'), res.set ? 'נגן את הסט' : 'נגן לפי הסדר'),
        res.set ? null : h('button', { class: 'btn btn-outline', type: 'button', onclick: () => H.player.playList(res.tracks, 0, { shuffle: true }) }, icon('shuffle'), 'ערבב'),
        h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => { H.player.enqueue(res.tracks); H.toast(`${H.songs(total)} נוספו לתור`, { icon: 'list-music' }); } }, icon('list-music'), 'הוספה לתור'),
        res.playlist_id
          ? h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => H.go('playlists', { id: res.playlist_id }) }, icon('pencil'), 'לסדר את הרשימה')
          : h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => H.saveAsPlaylist(res.tracks, res.understood || '') }, icon('list-plus'), 'שמירה כרשימה'),
        h('button', { class: 'btn btn-quiet', type: 'button', title: 'להעתיק את השירים האלה לנגן MP3 או לדיסק־און־קי',
          onclick: () => H.openExport(res.tracks, res.understood || res.title || '') }, icon('usb'), 'לנגן MP3')) : null);

    const parts = [head];
    const topic = (res.intent && res.intent.topic) || params.topic;
    const searching = res.intent && res.intent.action === 'search_song';
    const query = res.query || params.text || '';
    if (topic === VOCAL) parts.push(reviewPanel());
    if (res.set) {
      if (res.note) parts.push(h('p', { class: 'results-note' }, icon(total ? 'audio-lines' : 'info', 'icon-sm'), res.note));
      if (total) parts.push(H.trackList(res.tracks, { onPlay: (i) => H.player.playList(res.tracks, i, playOptions(res)) }));
      if (res.online) parts.push(setOnlinePanel(res));
      H.clear(root).append(...parts);
      return;
    }
    if (total) {
      if (res.near) parts.push(h('p', { class: 'results-note' }, icon('info', 'icon-sm'), res.note));
      parts.push(H.trackList(res.tracks));
      // Found something, but maybe not the one: YouTube is a click away.
      if (searching) parts.push(laterOnline(query));
      else if (topic && topic !== VOCAL) parts.push(laterOnline(topicQuery(topic), true));
    } else if (searching) {
      parts.push(H.emptyState(`„${query}” לא נמצא במחשב`,
        'אפשר להוריד מיוטיוב שיר מסוים, או לבחור שירים מכל הערוץ. כל הורדה נכנסת לספרייה ומסווגת מיד.'));
      parts.push(onlinePanel(query));
    } else {
      parts.push(H.emptyState(res.note || 'לא נמצאו שירים', null,
        h('button', { class: 'btn btn-outline', type: 'button', onclick: () => H.go('home') }, 'חזרה לבית')));
      if (topic && topic !== VOCAL) parts.push(laterOnline(topicQuery(topic), true));
    }
    H.clear(root).append(...parts);
  }

  // ------------------------------------------------------------ vocal review
  const VOCAL = 'ווקאלי';

  /**
   * Songs the detector heard as sung without instruments, waiting for the
   * listener's word. Until confirmed they are not suggested in the Omer
   * count or the Three Weeks (unless the listener allowed that in settings).
   */
  function reviewPanel() {
    const panel = h('section', { class: 'review', 'aria-label': 'שירים שזוהו מהשמע', hidden: true });
    api.vocalReview(300).then((r) => {
      if (!r.tracks.length) return;
      const list = h('div', { class: 'review-list', role: 'list' });
      const left = h('span', { class: 'muted num' });
      const ids = new Set(r.tracks.map((t) => t.id));
      const count = () => { left.textContent = ids.size ? H.songs(ids.size) : ''; if (!ids.size) panel.hidden = true; };
      const decide = async (tracks, value, rows) => {
        try {
          await api.confirmVocal(tracks.map((t) => t.id), value);
          for (const t of tracks) ids.delete(t.id);
          for (const row of rows) row.remove();
          count();
          H.toast(value ? `${H.songs(tracks.length)} נוספו לשירים הווקאליים` : `${H.songs(tracks.length)} סומנו כשירים עם כלים`, { icon: 'mic-vocal' });
          if (value) show({ ...lastParams, autoplay: false });
        } catch (err) {
          H.toast(`לא הצלחתי לשמור: ${err.message}`, { kind: 'bad' });
        }
      };
      const rows = r.tracks.map((t) => {
        const row = h('div', { class: 'review-row', role: 'listitem', 'data-id': t.id },
          H.cover(t),
          h('div', { class: 'track-main' },
            h('div', { class: 'track-title' }, H.trackTitle(t)),
            h('div', { class: 'track-sub' }, [t.artist, t.album].filter(Boolean).join(' · '))),
          h('span', { class: `badge${t.vocal === 'maybe' ? ' maybe' : ''}` }, t.vocal === 'maybe' ? 'אולי' : 'נשמע ווקאלי'),
          h('div', { class: 'actions' },
            h('button', { class: 'icon-btn', type: 'button', 'aria-label': `לשמוע את ${H.trackTitle(t)}`, onclick: () => H.player.playList([t], 0) }, icon('play', 'icon-sm')),
            h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: () => decide([t], true, [row]) }, icon('check', 'icon-sm'), 'ווקאלי'),
            h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => decide([t], false, [row]) }, 'יש כלים')));
        list.appendChild(row);
        return row;
      });
      const sure = r.tracks.filter((t) => t.vocal === 'vocal');
      panel.append(
        h('div', { class: 'review-head' },
          h('div', {},
            h('h2', {}, icon('ear'), 'זוהו מהשמע — כדאי לבדוק'),
            h('p', {}, 'המנגן הקשיב לשירים ושמע בהם שירה בלי כלי נגינה. אפשר לשמוע ולאשר; רק שירים שאושרו מוצעים בימי הספירה ובין המצרים.')),
          h('div', { class: 'results-actions' },
            left,
            sure.length ? h('button', { class: 'btn btn-outline btn-sm', type: 'button',
              onclick: () => decide(sure, true, rows.filter((row) => sure.some((t) => t.id === row.dataset.id))) },
            icon('check-check', 'icon-sm'), `לאשר את ${sure.length === 1 ? 'השיר הבטוח' : `${H.n(sure.length)} הבטוחים`}`) : null)),
        list);
      count();
      panel.hidden = false;
    }).catch(() => {});
    return panel;
  }

  // ------------------------------------------------------------ YouTube
  // Searching where the network blocks the app from searching YouTube: Google,
  // with "יוטיוב" added, inside the player's window (websearch.js); a click on
  // a YouTube result comes back here as a link, to the place the search
  // started from (electron/main.js).
  H.searchWeb = function searchWeb(query, holder) {
    H.go('websearch', { query, from: { view: H.currentView(), holder: holder || null } });
  };
  api.on('search-link', ({ url }) => {
    const from = H.webSearchFrom();
    const holder = from && from.holder;
    if (holder && holder.isConnected && from.view) {
      H.reveal(from.view);
      openLink(url, holder);
      holder.scrollIntoView({ block: 'nearest' });
    } else {
      H.go('results', { link: url });
    }
  });
  const searchButton = (query, holder, primary) => h('button', {
    class: `btn ${primary ? 'btn-primary btn-sm' : 'btn-quiet'}`, type: 'button', onclick: () => H.searchWeb(query, holder),
  }, icon('search', primary ? 'icon-sm' : ''), `לחפש „${query}” בגוגל`);
  const LONG = 15 * 60; // a show or a medley evening, not a song
  const SHORT = 60;     // a teaser

  /** 1.5.1: songs of a topic from YouTube, like the topics on the computer. */
  function topicQuery(topic) {
    const label = (H.topicLabels && H.topicLabels[topic]) || topic;
    return /^שירי |^ניגוני /.test(label) ? label : `שירי ${label}`;
  }

  /** Found songs on the computer, but maybe not the right one (or more of a topic).
   * Nothing is searched until the listener asks. */
  function laterOnline(query, more) {
    const slot = h('div', { class: 'results-more' });
    const btn = h('button', { class: 'btn btn-quiet', type: 'button' }, icon('search'),
      more ? `עוד „${query}” מיוטיוב` : `לא מה שחיפשת? לחפש את „${query}” ביוטיוב`);
    btn.addEventListener('click', () => slot.replaceChildren(onlinePanel(query)));
    slot.appendChild(btn);
    return slot;
  }

  /** One song from the list: download it, or open it on YouTube. */
  function songRow(item, primary) {
    return h('div', { class: `online-item${primary ? ' chosen' : ''}` },
      item.thumbnail ? h('img', { class: 'o-thumb', src: item.thumbnail, alt: '', loading: 'lazy' }) : null,
      h('div', { class: 'o-main' },
        h('div', { class: 'o-title', title: item.title }, item.display || item.title || item.id),
        h('div', { class: 'o-sub' }, [item.channel || item.uploader, item.duration ? H.clock(item.duration) : ''].filter(Boolean).join(' · '))),
      h('div', { class: 'o-actions' },
        h('button', { class: `btn ${primary ? 'btn-primary' : 'btn-outline'} btn-sm`, type: 'button', onclick: () => H.download(item) },
          icon('download', 'icon-sm'), 'הורדה לספרייה'),
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => H.player.playList([H.listenTrack(item)], 0) },
          icon('play', 'icon-sm'), 'להשמיע בלי לשמור'),
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.openExternal(item.url) }, 'ביוטיוב')));
  }

  /** The channel most of the results come from — usually the singer's own. */
  function mainChannel(results) {
    const counts = new Map();
    for (const r of results) {
      if (!r.channel_id) continue;
      const c = counts.get(r.channel_id) || { n: 0, name: r.channel || r.uploader, url: r.channel_url };
      c.n += 1;
      counts.set(r.channel_id, c);
    }
    let best = null;
    for (const [id, c] of counts) if (!best || c.n > best.n) best = { id, ...c };
    if (!best || best.n < 2 || best.n < results.length / 2) return null;
    return { ...best, url: best.url || `https://www.youtube.com/channel/${best.id}` };
  }

  /** Songs of a playlist or a channel, to tick and download together. */
  function listPicker(info, holder) {
    const items = info.results;
    const chosen = new Set(items.filter((it) => !it.in_library && !(it.duration && (it.duration > LONG || it.duration < SHORT))).map((it) => it.id));
    const count = h('span', { class: 'muted num' });
    const go = h('button', { class: 'btn btn-primary', type: 'button' }, icon('download'), '');
    const refresh = () => {
      count.textContent = `${H.n(chosen.size)} מתוך ${H.n(items.length)} נבחרו`;
      go.lastChild.textContent = chosen.size ? `להוריד ${chosen.size === 1 ? 'שיר אחד' : `${H.n(chosen.size)} שירים`}` : 'לא נבחרו שירים';
      go.disabled = !chosen.size;
    };
    const rows = items.map((it) => {
      const box = h('input', { type: 'checkbox', checked: chosen.has(it.id) ? '' : null, 'aria-label': it.title });
      box.checked = chosen.has(it.id);
      box.addEventListener('change', () => { if (box.checked) chosen.add(it.id); else chosen.delete(it.id); refresh(); });
      const notes = [it.duration ? H.clock(it.duration) : '', it.in_library ? 'כבר בספרייה' : '',
        it.duration > LONG ? 'ארוך — כנראה הופעה' : it.duration && it.duration < SHORT ? 'קצר מאוד' : ''].filter(Boolean).join(' · ');
      return h('label', { class: `pick${it.in_library ? ' have' : ''}` }, box,
        h('span', { class: 'pick-title', title: it.title }, it.display || it.title || it.id), h('span', { class: 'pick-sub num' }, notes));
    });
    const all = (on) => {
      chosen.clear();
      if (on) for (const it of items) if (!it.in_library) chosen.add(it.id);
      rows.forEach((row, i) => { row.querySelector('input').checked = chosen.has(items[i].id); });
      refresh();
    };
    go.addEventListener('click', () => {
      const picked = items.filter((it) => chosen.has(it.id));
      H.downloadMany(picked, info.title || info.artist || 'רשימה');
      holder.replaceChildren(h('p', { class: 'online-done' }, icon('circle-check', 'icon-sm'),
        `${H.songs(picked.length)} בדרך לספרייה. ההתקדמות במסך ההורדות.`,
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => H.go('downloads') }, 'למסך ההורדות')));
    });
    refresh();
    return h('div', { class: 'picker' },
      h('div', { class: 'picker-head' },
        h('div', {}, h('div', { class: 'picker-title' }, info.title || info.artist || 'רשימה'),
          h('div', { class: 'muted' }, count)),
        h('div', { class: 'picker-tools' },
          h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => all(true) }, icon('list-checks', 'icon-sm'), 'לבחור הכל'),
          h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => all(false) }, 'לנקות'))),
      h('div', { class: 'picker-list' }, rows),
      h('div', { class: 'picker-foot' }, go));
  }

  /** Read a pasted link and show what it is: a song, or a list to pick from. */
  async function openLink(url, holder) {
    holder.replaceChildren(h('p', { class: 'muted' }, icon('loader-circle', 'icon-sm spin'), 'קורא את הקישור…'));
    let info;
    try {
      info = await api.onlineLink(url, 300);
    } catch (err) {
      holder.replaceChildren(h('p', { class: 'online-error' }, err.message));
      return;
    }
    if (!info.ok) {
      holder.replaceChildren(h('p', { class: 'online-error' }, icon('circle-alert', 'icon-sm'),
        info.code === 'netfree' ? 'הקישור הזה חסום ברשת שלך (נטפרי או סינון דומה).' : info.message));
      return;
    }
    if (info.kind === 'video') {
      const item = info.results[0];
      holder.replaceChildren(songRow({ ...item, display: [info.artist, info.title].filter(Boolean).join(' - ') || item.display }, true));
      return;
    }
    if (!info.results.length) {
      holder.replaceChildren(h('p', { class: 'muted' }, 'אין ברשימה הזו שירים להורדה.'));
      return;
    }
    holder.replaceChildren(listPicker(info, holder));
  }

  /** Paste a YouTube link (a song, a playlist or a channel). When the app
   * window comes back to the front with such a link copied, it is filled in. */
  function pasteBox(holder, { prominent = false } = {}) {
    const input = h('input', { type: 'url', class: 'input', dir: 'ltr', placeholder: 'https://www.youtube.com/…', 'aria-label': 'קישור ליוטיוב' });
    const go = h('button', { class: `btn ${prominent ? 'btn-primary' : 'btn-outline'}`, type: 'button' }, icon('link'), 'להמשיך');
    const run = () => { if (input.value.trim()) openLink(input.value.trim(), holder); };
    go.addEventListener('click', run);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
    const paste = h('button', { class: 'btn btn-quiet', type: 'button', title: 'להדביק את הקישור שהעתקת' }, icon('clipboard-paste'), 'להדביק');
    const fromClipboard = async (auto) => {
      const link = await api.clipboardLink().catch(() => '');
      if (link && link !== input.dataset.last) {
        input.value = link;
        input.dataset.last = link;
        run();
      } else if (!auto && !link) {
        H.toast('אין בלוח קישור ליוטיוב. מעתיקים את הקישור בדפדפן ומדביקים כאן.', { icon: 'clipboard-paste' });
      }
    };
    paste.addEventListener('click', () => fromClipboard(false));
    const onFocus = () => {
      if (!document.body.contains(input)) { window.removeEventListener('focus', onFocus); return; }
      if (!input.value.trim()) fromClipboard(true);
    };
    window.addEventListener('focus', onFocus);
    return h('div', { class: `paste${prominent ? ' prominent' : ''}` },
      h('label', { class: 'paste-label' }, icon('link', 'icon-sm'), 'יש קישור? מדביקים כאן קישור לשיר, לפלייליסט או לערוץ ביוטיוב:'),
      h('div', { class: 'paste-row' }, input, paste, go));
  }

  /** A YouTube result as a song to play without saving it. */
  H.listenTrack = function listenTrack(item) {
    return {
      id: `yt:${item.id}`, listen: true, result: item, path: '',
      title: item.display || item.title || item.id, artist: item.channel || item.uploader || '',
      duration: item.duration || null, topic: null, tags: [], favorite: false,
    };
  };

  /** Not enough songs on the computer for the set: YouTube, in the style of
   * the singers the listener plays most — to listen without saving, or to
   * download into the library. */
  function setOnlinePanel(res) {
    const o = res.online;
    const list = h('div', { class: 'online-list' });
    const status = h('p', { class: 'muted' }, icon('loader-circle', 'icon-sm spin'), 'מחפש ביוטיוב…');
    const actions = h('div', { class: 'results-actions' });
    const style = o.artists && o.artists.length
      ? `בסגנון של מה שאתה שומע: ${o.artists.slice(0, 3).join(', ')}.`
      : 'לפי האירוע (עוד אין במחשב מספיק שירים כדי לדעת מה הסגנון שלך).';
    const linkResult = h('div', { class: 'link-result' });
    const paste = pasteBox(linkResult);
    const panel = h('section', { class: 'online set-online', 'aria-label': 'יוטיוב' },
      h('div', { class: 'online-head' }, icon('cloud-download'),
        h('h3', {}, res.tracks.length ? `עוד שירים ל${o.label} מיוטיוב` : `שירים ל${o.label} מיוטיוב`)),
      h('p', { class: 'muted' }, style, ' אפשר להשמיע בלי לשמור במחשב, או להוריד לספרייה.'),
      status, actions, list, paste, linkResult);
    api.onlineSet(o.event, o.topic).then((r) => {
      if (r.blocked || r.code === 'netfree') {
        status.replaceChildren(h('div', { class: 'notice' }, icon('shield-alert'),
          h('div', {},
            h('strong', {}, 'החיפוש ביוטיוב חסום ברשת שלך (נטפרי או סינון דומה).'),
            h('p', {}, 'אפשר לחפש בגוגל כאן בתוך המנגן וללחוץ על התוצאה מיוטיוב, או להדביק קישור לשיר, לפלייליסט או לערוץ.'),
            searchButton((r.queries || [])[0] || o.label, linkResult, true))));
        paste.classList.add('prominent');
        return;
      }
      if (!r.ok || !r.results.length) {
        status.replaceChildren(r.code === 'network' ? 'אין כרגע חיבור לרשת.' : (r.message || 'לא נמצאו שירים ביוטיוב.'));
        return;
      }
      status.replaceChildren(`${H.songs(r.results.length)} מיוטיוב.`);
      const fresh = r.results.filter((it) => !it.in_library);
      const listenAll = () => H.player.playList([...res.tracks, ...fresh.map(H.listenTrack)], 0,
        { shuffle: false, crossfade: res.set ? res.set.crossfade : 6 });
      actions.replaceChildren(
        h('button', { class: 'btn btn-primary', type: 'button', onclick: listenAll }, icon('play'),
          res.tracks.length ? 'להשמיע את הסט עם השירים מיוטיוב' : 'להשמיע הכל בלי לשמור'),
        h('button', { class: 'btn btn-outline', type: 'button', onclick: () => H.downloadMany(fresh, `${o.label} מיוטיוב`) },
          icon('download'), `להוריד הכל לספרייה (${H.n(fresh.length)})`));
      r.results.forEach((item) => list.appendChild(songRow(item, false)));
    }).catch((err) => status.replaceChildren(err.message));
    return panel;
  }

  function onlinePanel(query) {
    const list = h('div', { class: 'online-list' });
    const status = h('p', { class: 'muted' }, icon('loader-circle', 'icon-sm spin'), 'מחפש ביוטיוב…');
    const channelSlot = h('div', {});
    const linkResult = h('div', { class: 'link-result' });
    const browserBtn = searchButton(query, linkResult, false);
    const paste = pasteBox(linkResult);
    const panel = h('section', { class: 'online', 'aria-label': 'יוטיוב' },
      h('div', { class: 'online-head' }, icon('search'), h('h3', {}, `ביוטיוב: ${query}`)),
      status, channelSlot, list, paste, linkResult, h('div', { class: 'online-foot' }, browserBtn));

    api.onlineSearch(query, 8).then((r) => {
      if (!r.available) {
        status.replaceChildren('רכיב ההורדה לא מותקן בגרסה הזו, אז אפשר רק לחפש בגוגל.');
        return;
      }
      if (r.blocked || r.code === 'netfree') {
        // Not a fault: the network's filter does not let programs search
        // YouTube. The app does not go around it; the browser can search.
        status.replaceChildren(h('div', { class: 'notice' }, icon('shield-alert'),
          h('div', {},
            h('strong', {}, 'החיפוש ביוטיוב חסום ברשת שלך (נטפרי או סינון דומה).'),
            h('p', {}, 'זו הגדרה של הרשת, והמנגן לא עוקף אותה. אפשר לחפש בגוגל כאן בתוך המנגן וללחוץ על התוצאה מיוטיוב, או להדביק קישור לשיר או לערוץ. ההורדה עצמה עובדת לשירים שהרשת מתירה.'),
            searchButton(query, linkResult, true))));
        paste.classList.add('prominent');
        return;
      }
      if (!r.ok || !r.results.length) {
        status.replaceChildren(r.code === 'network' ? 'אין כרגע חיבור לרשת. החיפוש יעבוד כשהמחשב יתחבר.' : (r.message || 'לא נמצאו תוצאות.'));
        return;
      }
      status.replaceChildren('התוצאה הראשונה היא הכי מתאימה. אפשר להוריד כל אחת מהן.');
      const channel = mainChannel(r.results);
      if (channel) {
        const pickHolder = h('div', {});
        channelSlot.replaceChildren(h('div', { class: 'channel-card' },
          h('div', { class: 'channel-icon' }, icon('tv')),
          h('div', { class: 'channel-main' },
            h('div', { class: 'channel-name' }, `הערוץ של ${channel.name}`),
            h('div', { class: 'muted' }, 'כל השירים שהערוץ העלה — בוחרים מה להוריד.')),
          h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: () => openLink(channel.url, pickHolder) },
            icon('list-checks', 'icon-sm'), 'לבחור שירים מהערוץ')), pickHolder);
      }
      r.results.forEach((item, i) => list.appendChild(songRow(item, i === 0)));
    }).catch((err) => { status.replaceChildren(`החיפוש נכשל: ${err.message}`); });
    return panel;
  }

  H.views = H.views || {};
  H.views.results = { show, current: () => current };
})();
