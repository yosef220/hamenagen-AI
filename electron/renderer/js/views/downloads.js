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
        H.toast(`ההורדה נכשלה: ${job.message}`, { kind: 'bad' });
      }
    } catch (err) {
      job.status = 'failed';
      job.message = err.message;
      H.toast(`ההורדה נכשלה: ${err.message}`, { kind: 'bad' });
    }
    badge();
    redraw();
  };

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

  function stateText(job) {
    switch (job.status) {
      case 'queued': return 'מתחיל…';
      case 'downloading': return job.percent != null ? `מוריד · ${Math.round(job.percent)}%` : 'מוריד…';
      case 'postprocessing': return 'ממיר לקובץ שמע…';
      case 'done': return 'נוסף לספרייה';
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

  async function redraw() {
    if (root.hidden) return;
    let past = [];
    try {
      past = (await api.listTracks({ source: 'youtube', sort: 'added', descending: true, limit: 200 })).tracks;
    } catch { /* ignore */ }
    const folder = (H.appInfo && H.appInfo.downloads_dir) || '';
    H.clear(root).append(
      h('header', { class: 'page-head' },
        h('h1', {}, 'הורדות'),
        h('div', { class: 'page-meta' }, 'שירים שלא נמצאו במחשב ונמצאו ברשת. כל הורדה נכנסת לספרייה ומסווגת מיד.'),
        h('div', { class: 'page-actions' },
          folder ? h('button', { class: 'btn btn-outline', type: 'button', onclick: () => api.openFolder(folder) }, icon('folder-open'), 'תיקיית ההורדות') : null)),
      jobs.length
        ? h('section', { class: 'section', 'aria-label': 'עכשיו' }, h('div', { class: 'section-head' }, h('h2', {}, 'בהפעלה הזו')), h('div', { class: 'dl-list' }, jobs.map(jobRow)))
        : H.emptyState('אין הורדות פעילות', 'כשבקשה לא מוצאת שיר במחשב, המנגן מציע לחפש אותו ברשת ולהוריד.'),
      past.length
        ? h('section', { class: 'section', 'aria-label': 'הורדו בעבר' }, h('div', { class: 'section-head' }, h('h2', {}, 'הורדו בעבר'), h('span', { class: 'muted num' }, H.songs(past.length))), H.trackList(past))
        : null,
    );
  }

  H.views = H.views || {};
  H.views.downloads = { show: redraw };
})();
