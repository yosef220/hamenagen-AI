'use strict';

/*
 * Downloads: songs fetched from the network in this session, with live
 * progress, and everything downloaded before.
 */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-downloads');
  const jobs = []; // { id, title, status, percent, message, track }

  function badge() {
    const running = jobs.filter((j) => j.status === 'downloading' || j.status === 'postprocessing' || j.status === 'queued').length;
    const el = H.$('#nav-downloads');
    el.hidden = !running;
    el.textContent = running ? String(running) : '';
  }

  /** Download a search result into the library (spec §11). */
  H.download = async function download(result) {
    const id = `${result.id || 'dl'}-${Date.now()}`;
    const job = { id, title: result.title || result.id, status: 'queued', percent: null, message: '', track: null };
    jobs.unshift(job);
    badge();
    H.toast(`מוריד: ${job.title}`, { icon: 'download', action: { label: 'למסך ההורדות', fn: () => H.go('downloads') } });
    redraw();
    try {
      const res = await api.onlineDownload(result, id);
      job.status = res.ok ? 'done' : 'failed';
      job.message = res.message || '';
      job.track = res.track;
      if (res.ok && res.track) {
        const settings = H.settings || {};
        if (settings.autoplay_after_download !== false) H.player.playList([res.track], 0);
        H.toast(`"${H.trackTitle(res.track)}" נוסף לספרייה`, { icon: 'circle-check' });
        api.emit('library-changed', {});
      } else if (!res.ok) {
        if (res.blocked) job.message = 'הסרטון הזה חסום ברשת שלך (נטפרי או סינון דומה).';
        H.toast(res.blocked ? `„${job.title}” חסום ברשת שלך` : `ההורדה נכשלה: ${job.message}`, { kind: 'bad' });
      }
    } catch (err) {
      job.status = 'failed';
      job.message = err.message;
      H.toast(`ההורדה נכשלה: ${err.message}`, { kind: 'bad' });
    }
    badge();
    redraw();
  };

  /** Download several songs one after another (a channel, a playlist).
   * Songs already in the library are skipped; one the network blocks is
   * marked and the rest go on. */
  let batch = null; // { id, label, total, jobs: Map(videoId → job) }
  H.downloadMany = async function downloadMany(items, label) {
    if (!items.length) return;
    if (batch) {
      H.toast('כבר יורדים שירים מרשימה אחרת. אפשר להוסיף עוד כשהיא תסתיים.', { icon: 'download' });
      return;
    }
    const id = `batch-${Date.now()}`;
    batch = { id, label, total: items.length, jobs: new Map() };
    for (const item of items.slice().reverse()) {
      const job = { id: `${id}-${item.id}`, title: item.title || item.id, status: 'queued', percent: null, message: '', track: null };
      batch.jobs.set(item.id, job);
      jobs.unshift(job);
    }
    badge();
    redraw();
    H.toast(`${H.songs(items.length)} מ„${label}” בדרך לספרייה`, { icon: 'download', action: { label: 'למסך ההורדות', fn: () => H.go('downloads') } });
    try {
      const res = await api.downloadBatch(items, id);
      if (!res.started) {
        for (const item of items) { const j = batch.jobs.get(item.id); j.status = 'failed'; j.message = 'הורדה אחרת כבר רצה'; }
        batch = null;
        badge();
        redraw();
      }
    } catch (err) {
      batch = null;
      H.toast(`ההורדה לא התחילה: ${err.message}`, { kind: 'bad' });
    }
  };

  api.on('download_batch', (msg) => {
    if (!batch || msg.batch_id !== batch.id) return;
    const job = batch.jobs.get(msg.id);
    if (!job) return;
    if (msg.type === 'progress') {
      if (msg.status === 'downloading') { job.status = 'downloading'; job.percent = msg.percent; }
      else if (msg.status === 'postprocessing') job.status = 'postprocessing';
    } else if (msg.status === 'started') {
      job.status = 'downloading';
    } else if (msg.status === 'done') {
      job.status = 'done';
      job.track = msg.track;
      api.emit('library-changed', {});
    } else if (msg.status === 'skipped') {
      job.status = 'done';
      job.message = 'כבר היה בספרייה';
    } else if (msg.status === 'failed') {
      job.status = 'failed';
      job.message = msg.blocked ? 'חסום ברשת שלך' : (msg.message || 'נכשל');
    }
    badge();
    if (!root.hidden) updateJob(job);
  });

  api.on('download_batch_done', (msg) => {
    if (!batch || msg.batch_id !== batch.id) return;
    for (const job of batch.jobs.values()) {
      if (['queued', 'downloading', 'postprocessing'].includes(job.status)) { job.status = 'failed'; job.message = msg.stopped ? 'נעצר' : 'לא ירד'; }
    }
    const parts = [`ירדו ${H.songs(msg.downloaded || 0)}`];
    if (msg.skipped) parts.push(`${H.n(msg.skipped)} כבר היו`);
    if (msg.blocked) parts.push(`${H.n(msg.blocked)} חסומים ברשת`);
    else if (msg.failed) parts.push(`${H.n(msg.failed)} נכשלו`);
    H.toast(`${batch.label}: ${parts.join(' · ')}`, { icon: msg.error ? 'circle-alert' : 'circle-check', kind: msg.error ? 'bad' : undefined });
    batch = null;
    badge();
    redraw();
  });

  api.on('download_progress', (msg) => {
    const job = jobs.find((j) => j.id === msg.download_id);
    if (!job) return;
    if (msg.status === 'downloading') {
      job.status = 'downloading';
      job.percent = msg.percent;
    } else if (msg.status === 'postprocessing') {
      job.status = 'postprocessing';
    }
    badge();
    if (!root.hidden) updateJob(job);
  });

  // ------------------------------------------------------------ a singer's songs (1.7)
  // A singer's name finds the singer's own channel on YouTube and lists every
  // song it uploaded, to tick and download; songs already here are marked.
  // Built once, so a download starting or ending never wipes what is picked.
  const singerHolder = h('div', { class: 'singer-result' });
  const singerInput = h('input', { class: 'input', type: 'text', placeholder: 'שם של זמר, למשל: אלי הרצליך',
    'aria-label': 'שם של זמר', maxlength: '80' });
  const singerGo = h('button', { class: 'btn btn-primary', type: 'submit' }, icon('list-checks'), 'כל השירים שלו');
  const singerForm = h('form', { class: 'singer-form', role: 'search' }, icon('mic-vocal'), singerInput, singerGo);
  singerForm.addEventListener('submit', (e) => { e.preventDefault(); showSinger(singerInput.value); });
  const singerSection = h('section', { class: 'section singer-section', 'aria-label': 'שירים של זמר' },
    h('div', { class: 'section-head' }, h('h2', {}, 'כל השירים של זמר')),
    h('p', { class: 'muted' }, 'כותבים שם של זמר, והמנגן מוצא את הערוץ שלו ביוטיוב ומציג את כל השירים שהעלה — רק להורדה, שום דבר לא מתנגן. בוחרים מה להוריד; מה שכבר במחשב מסומן. אפשר גם לעקוב אחרי הזמר, ושיר חדש שלו יקפוץ עם כפתור הורדה.'),
    singerForm, singerHolder);

  async function showSinger(name) {
    name = (name || '').trim();
    if (!name) { singerInput.focus(); return; }
    singerGo.disabled = true;
    singerHolder.replaceChildren(h('p', { class: 'muted' }, icon('loader-circle', 'icon-sm spin'), `מחפש את הערוץ של ${name} ביוטיוב…`));
    try {
      const info = await api.singerSongs(name, 300);
      if (!info.ok) {
        singerHolder.replaceChildren(h('p', { class: 'online-error' }, icon('circle-alert', 'icon-sm'),
          info.blocked || info.code === 'netfree'
            ? 'החיפוש ביוטיוב חסום ברשת שלך (נטפרי או סינון דומה). אפשר להדביק קישור לערוץ של הזמר בעמוד החיפוש.'
            : info.message || 'לא נמצא'));
        return;
      }
      if (!info.results.length) {
        singerHolder.replaceChildren(h('p', { class: 'muted' }, `בערוץ של ${info.channel.name} אין שירים להורדה.`));
        return;
      }
      singerHolder.replaceChildren(H.songPicker(info, singerHolder, { extra: followButton(info.channel, info.followed) }));
    } catch (err) {
      singerHolder.replaceChildren(h('p', { class: 'online-error' }, `החיפוש נכשל: ${err.message}`));
    } finally {
      singerGo.disabled = false;
    }
  }

  function followButton(channel, followed) {
    const btn = h('button', { class: 'btn btn-outline btn-sm', type: 'button', 'aria-pressed': followed ? 'true' : 'false' });
    const paint = (on) => {
      btn.replaceChildren(icon(on ? 'bell-ring' : 'bell-plus', 'icon-sm'), on ? 'עוקב: שירים חדשים יופיעו כאן' : 'לעקוב אחרי שירים חדשים');
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    };
    paint(followed);
    btn.addEventListener('click', async () => {
      const on = btn.getAttribute('aria-pressed') !== 'true';
      btn.disabled = true;
      try {
        await api.followSinger(channel.name, channel.id, on);
        paint(on);
        H.toast(on ? `מעכשיו שירים חדשים של ${channel.name} יופיעו במסך ההורדות` : `הפסקת לעקוב אחרי ${channel.name}`, { icon: 'bell-ring' });
        refreshNew(false);
      } catch (err) {
        H.toast(`לא נשמר: ${err.message}`, { kind: 'bad' });
      } finally {
        btn.disabled = false;
      }
    });
    return btn;
  }

  // New songs from the singers the listener follows (checked every few hours).
  const newSection = h('section', { class: 'section new-songs', 'aria-label': 'שירים חדשים', hidden: true });
  async function refreshNew(force) {
    let r;
    try {
      r = await api.followedNew(!!force);
    } catch {
      return;
    }
    if (!r.singers.length) { newSection.hidden = true; return; }
    newSection.hidden = false;
    const chips = h('div', { class: 'chips' }, r.singers.map((s) => h('span', { class: 'chip follow-chip' }, s.name,
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': `להפסיק לעקוב אחרי ${s.name}`, onclick: async () => {
        await api.followSinger(s.name, s.channel_id, false).catch(() => null);
        refreshNew(false);
      } }, icon('x', 'icon-sm')))));
    const rows = r.new.map((item) => h('div', { class: 'online-item' },
      item.thumbnail ? h('img', { class: 'o-thumb', src: item.thumbnail, alt: '', loading: 'lazy' }) : null,
      h('div', { class: 'o-main' },
        h('div', { class: 'o-title', title: item.title }, item.display || item.title),
        h('div', { class: 'o-sub' }, [item.singer, H.songDate(item)].filter(Boolean).join(' · '))),
      h('div', { class: 'o-actions' },
        h('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: () => H.download(item) }, icon('download', 'icon-sm'), 'הורדה לספרייה'),
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => H.player.playList([H.listenTrack(item)], 0) }, icon('play', 'icon-sm'), 'להשמיע בלי לשמור'),
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: async () => { await api.dismissNew(item.id).catch(() => null); refreshNew(false); } }, 'לא מעניין'))));
    newSection.replaceChildren(
      h('div', { class: 'section-head' }, h('h2', {}, 'שירים חדשים מזמרים שאתה עוקב אחריהם'),
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => refreshNew(true) }, icon('refresh-cw', 'icon-sm'), 'לבדוק עכשיו')),
      chips,
      rows.length ? h('div', { class: 'online-list' }, rows) : h('p', { class: 'muted' }, 'אין כרגע שירים חדשים. המנגן בודק כל כמה שעות.'));
  }

  // 1.7: a new song from a followed singer pops up, with a button to download
  // it — checked a little after the player opens, then every hour (the core
  // reads each singer's channel at most every few hours). Each song once.
  async function announceNew() {
    let r;
    try {
      r = await api.followedNew(false);
    } catch {
      return;
    }
    const told = new Set(H.storage.get('newSongsTold', []));
    const fresh = (r.new || []).filter((it) => !told.has(it.id));
    if (!fresh.length) return;
    for (const it of fresh) told.add(it.id);
    H.storage.set('newSongsTold', [...told].slice(-500));
    if (!root.hidden) refreshNew(false);
    if (fresh.length === 1) {
      const it = fresh[0];
      H.toast(`יצא שיר חדש של ${it.singer}: ${it.display || it.title}`, {
        icon: 'bell-ring', ms: 20000, action: { label: 'להוריד', fn: () => H.download(it) },
      });
    } else {
      const singers = [...new Set(fresh.map((it) => it.singer))].join(', ');
      H.toast(`יצאו ${H.songs(fresh.length)} חדשים של ${singers}`, {
        icon: 'bell-ring', ms: 20000, action: { label: 'להציג ולהוריד', fn: () => H.go('downloads') },
      });
    }
  }
  setTimeout(announceNew, 20000);
  setInterval(announceNew, 60 * 60 * 1000);

  function stateText(job) {
    switch (job.status) {
      case 'queued': return 'מתחיל…';
      case 'downloading': return job.percent != null ? `מוריד · ${Math.round(job.percent)}%` : 'מוריד…';
      case 'postprocessing': return 'ממיר ל-MP3 ומכניס תמונה…';
      case 'done': return job.message || 'נוסף לספרייה';
      default: return job.message || 'נכשל';
    }
  }

  function jobRow(job) {
    const row = h('div', { class: 'dl', 'data-job': job.id },
      h('div', { class: 'dl-main', style: { 'min-width': '0' } },
        h('div', { class: 'dl-title' }, job.title),
        h('div', { class: `dl-state${job.status === 'failed' ? ' bad' : job.status === 'done' ? ' good' : ''}` }, stateText(job))),
      h('div', {},
        job.status === 'done' && job.track
          ? h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => H.player.playList([job.track], 0) }, icon('play', 'icon-sm'), 'נגן')
          : null,
        job.status === 'done' && job.track
          ? h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => api.showInFolder(job.track.path) }, icon('folder-open', 'icon-sm'), 'בתיקייה')
          : null),
      ['queued', 'downloading', 'postprocessing'].includes(job.status)
        ? h('div', { class: `bar${job.percent == null || job.status !== 'downloading' ? ' indeterminate' : ''}` }, h('span', { style: { width: `${job.percent || 0}%` } }))
        : null);
    return row;
  }

  function updateJob(job) {
    const old = root.querySelector(`[data-job="${CSS.escape(job.id)}"]`);
    if (old) old.replaceWith(jobRow(job));
  }

  let refreshedNew = false;
  async function redraw() {
    if (root.hidden) return;
    let past = [];
    try {
      past = (await api.listTracks({ source: 'youtube', sort: 'added', descending: true, limit: 200 })).tracks;
    } catch { /* ignore */ }
    const folder = (H.appInfo && H.appInfo.downloads_dir) || '';
    if (!refreshedNew) { refreshedNew = true; refreshNew(false); }
    H.clear(root).append(
      h('header', { class: 'page-head' },
        h('h1', {}, 'הורדות'),
        h('div', { class: 'page-meta' }, 'שירים שלא נמצאו במחשב ונמצאו ברשת. כל הורדה נכנסת לספרייה ומסווגת מיד.'),
        h('div', { class: 'page-actions' },
          batch ? h('button', { class: 'btn btn-outline', type: 'button', onclick: () => { api.stopDownloads().catch(() => {}); H.toast('עוצר אחרי השיר הנוכחי', { icon: 'circle-stop' }); } },
            icon('circle-stop'), 'לעצור את הרשימה') : null,
          folder ? h('button', { class: 'btn btn-outline', type: 'button', onclick: () => api.openFolder(folder) }, icon('folder-open'), 'תיקיית ההורדות') : null)),
      singerSection,
      newSection,
      jobs.length
        ? h('section', { class: 'section', 'aria-label': 'עכשיו' }, h('div', { class: 'section-head' }, h('h2', {}, 'בהפעלה הזו')), h('div', { class: 'dl-list' }, jobs.map(jobRow)))
        : H.emptyState('אין הורדות פעילות', 'כשבקשה לא מוצאת שיר במחשב, המנגן מציע לחפש אותו ברשת ולהוריד.'),
      past.length
        ? h('section', { class: 'section', 'aria-label': 'הורדו בעבר' }, h('div', { class: 'section-head' }, h('h2', {}, 'הורדו בעבר'), h('span', { class: 'muted num' }, H.songs(past.length))), H.trackList(past))
        : null,
    );
  }

  H.views = H.views || {};
  H.views.downloads = { show: () => { refreshedNew = false; return redraw(); } };
})();
