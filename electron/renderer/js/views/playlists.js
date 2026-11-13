'use strict';

/*
 * Saved playlists: the page that lists them, one playlist with its songs in
 * the order the listener dragged them into, and the dialogs that add songs to
 * a playlist or save a list (the queue, a request's answer) under a name.
 */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-playlists');
  let current = null;   // the playlist on screen: { id, name, tracks, … }

  // ------------------------------------------------------------ dialogs
  const dialog = h('dialog', { class: 'dialog dialog-narrow', 'aria-labelledby': 'pl-dialog-title' });
  document.body.appendChild(dialog);
  dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });

  function openDialog(title, ...content) {
    H.clear(dialog).append(
      h('header', { class: 'dialog-head' },
        h('h2', { id: 'pl-dialog-title' }, title),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'סגירה', onclick: () => dialog.close() }, icon('x'))),
      h('div', { class: 'dialog-body' }, ...content));
    if (!dialog.open) dialog.showModal();
  }

  function nameForm(placeholder, value, button, onSubmit) {
    const input = h('input', { class: 'input', type: 'text', placeholder, value: value || '', 'aria-label': placeholder, maxlength: '80' });
    const form = h('form', { class: 'pl-form' }, input,
      h('button', { class: 'btn btn-primary btn-sm', type: 'submit' }, button));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      form.querySelector('button').disabled = true;
      await onSubmit(name);
    });
    setTimeout(() => { input.focus(); input.select(); }, 30);
    return form;
  }

  /** Add songs to a saved playlist, or to a new one. */
  H.addToPlaylist = async function addToPlaylist(tracks) {
    const ids = tracks.map((t) => t.id);
    const what = tracks.length === 1 ? `„${H.trackTitle(tracks[0])}”` : H.songs(tracks.length);
    const { playlists } = await api.playlists().catch(() => ({ playlists: [] }));
    const list = h('div', { class: 'pl-choices', role: 'list' },
      playlists.map((p) => h('button', { class: 'pl-choice', type: 'button', role: 'listitem', onclick: async () => {
        const r = await api.playlistAdd(p.id, ids).catch((err) => ({ ok: false, message: err.message }));
        dialog.close();
        if (!r.ok) { H.toast(r.message || 'לא הצלחתי להוסיף', { kind: 'bad' }); return; }
        H.toast(r.added ? `${what} נוסף לרשימה „${r.name}”` : `${what} כבר ברשימה „${r.name}”`, { icon: 'list-music' });
        if (current && current.id === p.id) show({ id: p.id });
      } }, icon('list-music', 'icon-sm'), h('span', { class: 'pl-choice-name' }, p.name), h('span', { class: 'pl-choice-n num' }, H.songs(p.count)))));
    openDialog('הוספה לרשימה',
      playlists.length ? list : h('p', { class: 'muted' }, 'עוד אין רשימות שמורות.'),
      h('div', { class: 'pl-new-label' }, 'רשימה חדשה'),
      nameForm('שם לרשימה, למשל „שבת בבוקר”', '', 'יצירה והוספה', async (name) => {
        const r = await api.playlistCreate(name, ids).catch((err) => ({ ok: false, message: err.message }));
        dialog.close();
        if (r.ok) H.toast(`נוצרה הרשימה „${r.name}” עם ${what}`, { icon: 'list-music' });
        else H.toast(r.message || 'לא הצלחתי ליצור את הרשימה', { kind: 'bad' });
      }));
  };

  /** Save a whole list (the queue, the answer to a request) under a name. */
  H.saveAsPlaylist = function saveAsPlaylist(tracks, suggested) {
    openDialog('שמירה כרשימה',
      h('p', { class: 'muted' }, `${H.songs(tracks.length)} יישמרו ברשימה, בסדר הזה.`),
      nameForm('שם לרשימה', suggested || '', 'שמירה', async (name) => {
        const r = await api.playlistCreate(name, tracks.map((t) => t.id)).catch((err) => ({ ok: false, message: err.message }));
        dialog.close();
        if (r.ok) {
          H.toast(`נשמרה הרשימה „${r.name}”`, { icon: 'list-music' });
        } else {
          H.toast(r.message || 'לא הצלחתי לשמור', { kind: 'bad' });
        }
      }));
  };

  // ------------------------------------------------------------ the list of playlists
  function mosaic(p) {
    const keys = p.covers || [];
    if (!keys.length) return h('div', { class: 'pl-art', 'aria-hidden': 'true' }, h('span', { class: 'pl-letter' }, H.letter(p.name)));
    const cells = [0, 1, 2, 3].map((i) => {
      const key = keys[i % keys.length];
      return h('img', { src: `cover://${key}/`, alt: '', loading: 'lazy', decoding: 'async' });
    });
    return h('div', { class: `pl-art${keys.length === 1 ? ' one' : ''}`, 'aria-hidden': 'true' }, keys.length === 1 ? cells[0] : cells);
  }

  async function renderAll() {
    current = null;
    const { playlists } = await api.playlists().catch(() => ({ playlists: [] }));
    const newButton = h('button', { class: 'btn btn-primary', type: 'button', onclick: () => {
      openDialog('רשימה חדשה', nameForm('שם לרשימה', '', 'יצירה', async (name) => {
        const r = await api.playlistCreate(name, []).catch((err) => ({ ok: false, message: err.message }));
        dialog.close();
        if (r.ok) show({ id: r.id });
      }));
    } }, icon('plus'), 'רשימה חדשה');
    const grid = h('div', { class: 'pl-grid', role: 'list' },
      playlists.map((p) => h('button', { class: 'pl-card', type: 'button', role: 'listitem', onclick: () => show({ id: p.id }) },
        mosaic(p),
        h('div', { class: 'pl-name' }, p.name),
        h('div', { class: 'pl-meta num' }, p.count ? `${H.songs(p.count)} · ${H.span(p.seconds)}` : 'ריקה'))));
    H.clear(root).append(
      h('header', { class: 'page-head' },
        h('h1', {}, 'רשימות'),
        h('div', { class: 'page-meta' }, playlists.length ? `${H.n(playlists.length)} רשימות שמורות` : ''),
        h('div', { class: 'page-actions' }, newButton)),
      playlists.length ? grid : h('div', { class: 'empty-state' },
        icon('list-music', 'icon-xl'),
        h('h2', {}, 'עוד אין רשימות'),
        h('p', {}, 'יוצרים רשימה, ומוסיפים אליה שירים מהתפריט ⋯ של כל שיר. אפשר גם לשמור את התור, או תוצאה של בקשה, כרשימה. את הסדר משנים בגרירה.')));
  }

  // ------------------------------------------------------------ one playlist
  function orderFromList(list) {
    return Array.from(list.querySelectorAll('.track')).map((row) => row.dataset.id);
  }

  async function saveOrder(list) {
    const ids = orderFromList(list);
    const byId = new Map(current.tracks.map((t) => [t.id, t]));
    current.tracks = ids.map((id) => byId.get(id)).filter(Boolean);
    list.querySelectorAll('.track .idx-n').forEach((n, i) => { n.textContent = String(i + 1); });
    try {
      await api.playlistSetOrder(current.id, ids);
    } catch (err) {
      H.toast(`הסדר לא נשמר: ${err.message}`, { kind: 'bad' });
    }
  }

  function sortable(list) {
    let dragged = null;
    let moved = false;
    list.addEventListener('dragstart', (e) => {
      const row = e.target.closest('.track');
      if (!row) return;
      dragged = row;
      moved = false;
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', row.dataset.id);
    });
    list.addEventListener('dragover', (e) => {
      if (!dragged) return;
      e.preventDefault();
      const over = e.target.closest('.track');
      if (!over || over === dragged) return;
      const box = over.getBoundingClientRect();
      const after = e.clientY > box.top + box.height / 2;
      const ref = after ? over.nextSibling : over;
      if (ref !== dragged && ref !== dragged.nextSibling) {
        list.insertBefore(dragged, ref);
        moved = true;
      }
    });
    list.addEventListener('drop', (e) => e.preventDefault());
    list.addEventListener('dragend', () => {
      if (!dragged) return;
      dragged.classList.remove('dragging');
      dragged = null;
      if (moved) saveOrder(list);
    });
    // The keyboard: Alt+↑ / Alt+↓ moves the song.
    list.addEventListener('keydown', (e) => {
      if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
      const row = e.target.closest('.track');
      if (!row) return;
      e.preventDefault();
      const sibling = e.key === 'ArrowUp' ? row.previousElementSibling : row.nextElementSibling;
      if (!sibling) return;
      if (e.key === 'ArrowUp') list.insertBefore(row, sibling);
      else list.insertBefore(sibling, row);
      row.focus();
      saveOrder(list);
    });
  }

  function songRow(track, i, list) {
    const play = () => H.player.playList(current.tracks, current.tracks.findIndex((t) => t.id === track.id));
    const sub = [track.artist, track.album].filter(Boolean).join(' · ') || track.folder || '';
    const row = h('div', { class: 'track pl-row', role: 'listitem', tabindex: '0', draggable: 'true', 'data-id': track.id,
      'aria-label': `${H.trackTitle(track)}. אפשר לגרור, או להזיז עם Alt וחץ` },
      h('span', { class: 'pl-grip', 'aria-hidden': 'true' }, icon('grip-vertical', 'icon-sm')),
      h('div', { class: 'track-idx' },
        h('span', { class: 'idx-n' }, String(i + 1)),
        h('button', { class: 'icon-btn play-hint', type: 'button', 'aria-label': `נגן את ${H.trackTitle(track)}`, onclick: (e) => { e.stopPropagation(); play(); } }, icon('play', 'icon-sm'))),
      H.cover(track),
      h('div', { class: 'track-main' },
        h('div', { class: 'track-title', title: H.trackTitle(track) }, H.trackTitle(track)),
        sub ? h('div', { class: 'track-sub' }, sub) : null),
      h('div', { class: 'track-dur' }, track.duration ? H.clock(track.duration) : ''),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `להסיר את ${H.trackTitle(track)} מהרשימה`, onclick: (e) => {
        e.stopPropagation();
        row.remove();
        saveOrder(list);
        H.toast(`„${H.trackTitle(track)}” הוסר מהרשימה`, { icon: 'trash-2' });
      } }, icon('x', 'icon-sm')));
    row.addEventListener('dblclick', play);
    row.addEventListener('keydown', (e) => { if (e.key === 'Enter') play(); });
    row.addEventListener('contextmenu', (e) => { e.preventDefault(); H.openTrackMenu(track, { x: e.clientX, y: e.clientY }); });
    return row;
  }

  async function renderOne(id) {
    const res = await api.playlistGet(id).catch((err) => ({ ok: false, message: err.message }));
    if (!res.ok) { await renderAll(); return; }
    current = res;
    const titleBox = h('div', { class: 'pl-title-box' }, h('h1', { class: 'results-title' }, res.name));
    const rename = () => {
      H.clear(titleBox).append(nameForm('שם הרשימה', current.name, 'שמירה', async (name) => {
        const r = await api.playlistRename(current.id, name).catch(() => ({ ok: false }));
        if (r.ok) current.name = r.name;
        H.clear(titleBox).append(h('h1', { class: 'results-title' }, current.name));
      }));
    };
    const confirmDelete = h('div', { class: 'pl-confirm', hidden: true },
      h('span', {}, `למחוק את הרשימה „${res.name}”? השירים עצמם נשארים במחשב.`),
      h('button', { class: 'btn btn-outline btn-sm', type: 'button', onclick: async () => {
        await api.playlistDelete(current.id).catch(() => null);
        H.toast(`הרשימה „${current.name}” נמחקה`, { icon: 'trash-2' });
        renderAll();
      } }, 'כן, למחוק'),
      h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => { confirmDelete.hidden = true; } }, 'ביטול'));
    const total = res.tracks.length;
    const list = h('div', { class: 'tracks pl-tracks', role: 'list', 'aria-label': `השירים ברשימה ${res.name}` });
    res.tracks.forEach((t, i) => list.appendChild(songRow(t, i, list)));
    sortable(list);
    H.clear(root).append(
      h('header', { class: 'results-head' },
        h('button', { class: 'btn btn-quiet btn-sm pl-back', type: 'button', onclick: () => renderAll() }, icon('chevron-right', 'icon-sm'), 'כל הרשימות'),
        titleBox,
        h('div', { class: 'results-meta num' }, total ? `${H.songs(total)} · ${H.span(res.seconds)} · משנים סדר בגרירה` : 'הרשימה ריקה'),
        h('div', { class: 'results-actions' },
          total ? h('button', { class: 'btn btn-primary', type: 'button', onclick: () => H.player.playList(current.tracks, 0, { shuffle: false }) }, icon('play'), 'נגן לפי הסדר') : null,
          total ? h('button', { class: 'btn btn-outline', type: 'button', onclick: () => H.player.playList(current.tracks, 0, { shuffle: true }) }, icon('shuffle'), 'ערבב') : null,
          total ? h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => H.openExport(current.tracks, current.name) }, icon('usb'), 'לנגן MP3') : null,
          h('button', { class: 'btn btn-quiet', type: 'button', onclick: rename }, icon('pencil'), 'שינוי שם'),
          h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => { confirmDelete.hidden = false; } }, icon('trash-2'), 'מחיקה')),
        confirmDelete),
      total ? list : h('div', { class: 'empty-state' },
        icon('list-music', 'icon-xl'),
        h('p', {}, 'מוסיפים שירים מהתפריט ⋯ של כל שיר („הוספה לרשימה”), או שומרים את התור כרשימה.')));
    H.markActiveRows && H.markActiveRows();
  }

  async function show(params = {}) {
    if (params.id) await renderOne(params.id);
    else await renderAll();
  }

  H.views = H.views || {};
  H.views.playlists = { show, refresh: () => (current ? renderOne(current.id) : renderAll()) };
})();
