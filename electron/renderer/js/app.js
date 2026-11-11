'use strict';

/*
 * The app shell: navigation between views, the request flow, theme and text
 * size, the rail's library status, background work on start (scan, model,
 * update check), keyboard shortcuts, and the screen shown if the core fails.
 */
(function () {
  const { h, icon, api } = H;
  const views = H.views;
  let currentView = 'home';
  let lastParams = {};

  // ------------------------------------------------------------ navigation
  H.go = function go(name, params = {}) {
    if (!views[name]) return;
    currentView = name;
    lastParams = params;
    for (const section of H.$$('.view')) section.hidden = section.dataset.view !== name;
    const navName = name === 'results' ? null : name;
    for (const item of H.$$('.nav-item')) {
      if (item.dataset.view === navName) item.setAttribute('aria-current', 'page');
      else item.removeAttribute('aria-current');
    }
    H.$('#main').scrollTop = 0;
    views[name].show(params);
  };

  for (const item of H.$$('.nav-item')) item.addEventListener('click', () => H.go(item.dataset.view));

  /** A typed request: understand it and start playing (spec §8). */
  H.ask = function ask(text) {
    const clean = String(text || '').trim();
    if (!clean) return;
    H.go('results', { text: clean, autoplay: true });
  };

  /** Play a topic straight away (the luach's suggestion button). */
  H.playTopic = function playTopic(topic) {
    H.go('results', { kind: 'play_topic', topic, autoplay: true });
  };

  // ------------------------------------------------------------ theme and text
  H.applyTheme = function applyTheme(theme) {
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    api.setTheme(theme || 'system');
  };

  H.applyTextSize = function applyTextSize(size) {
    if (size === 'large' || size === 'xlarge') document.documentElement.dataset.text = size;
    else delete document.documentElement.dataset.text;
  };

  // ------------------------------------------------------------ rail status
  H.updateRail = function updateRail(overview) {
    if (!overview) return;
    const stats = overview.stats;
    H.$('#rail-count').textContent = stats.tracks
      ? `${H.songs(stats.tracks)} · ${H.span(stats.seconds)}`
      : 'הספרייה עוד ריקה';
    if (!overview.scanning && overview.last_scan_at && !scanning) {
      H.$('#rail-scan').replaceChildren(icon('check'), `נסרק ${H.ago(overview.last_scan_at)}`);
    }
  };

  async function refreshRail() {
    try { H.updateRail(await api.overview()); } catch { /* ignore */ }
  }

  // ------------------------------------------------------------ background scan
  let scanning = false;

  H.rescan = async function rescan(announce) {
    try {
      const res = await api.rescan();
      if (res.started) {
        scanning = true;
        H.$('#rail-scan').replaceChildren(icon('loader-circle', 'spin'), 'סורק את המחשב…');
        if (announce) H.toast('הסריקה רצה ברקע. אפשר להמשיך להאזין.', { icon: 'refresh-cw' });
      } else if (announce) {
        H.toast('סריקה כבר רצה ברקע.', { icon: 'refresh-cw' });
      }
    } catch (err) {
      H.toast(`הסריקה לא התחילה: ${err.message}`, { kind: 'bad' });
    }
  };

  api.on('scan_progress', (msg) => {
    scanning = true;
    H.$('#rail-scan').replaceChildren(icon('loader-circle', 'spin'),
      msg.files ? `סורק… ${H.n(msg.files)} קבצים` : 'סורק את המחשב…');
  });

  api.on('scan_done', async (msg) => {
    scanning = false;
    if (msg.error) {
      H.$('#rail-scan').replaceChildren(icon('triangle-alert'), 'הסריקה נכשלה');
      H.toast(`הסריקה נכשלה: ${msg.error}`, { kind: 'bad' });
      return;
    }
    H.$('#rail-scan').replaceChildren(icon('check'), 'נסרק עכשיו');
    await refreshRail();
    if (msg.added) H.toast(`${H.songs(msg.added)} חדשים נוספו לספרייה`, { icon: 'music-2' });
    // Lists that show the library catch up with the scan.
    if (['home', 'library', 'topics'].includes(currentView)) views[currentView].refresh && views[currentView].refresh();
    ensureModel();
  });

  api.on('library-changed', () => { refreshRail(); });
  api.on('played', () => { if (currentView === 'home') views.home.refresh(); });

  // ------------------------------------------------------------ AI model
  let modelAsked = false;

  async function ensureModel() {
    if (modelAsked) return;
    let st;
    try { st = await api.classifierStatus(); } catch { return; }
    if (!st.enabled || st.loaded) return;
    modelAsked = true;
    api.installModel().catch(() => {});
  }

  api.on('model_install', (msg) => {
    const el = H.$('#rail-model');
    if (msg.status === 'downloading') {
      const pct = typeof msg.percent === 'number' ? ` · ${Math.floor(msg.percent)}%` : '';
      el.replaceChildren(icon('loader-circle', 'spin'), `מוריד את מודל הסיווג (פעם אחת)${pct}`);
    } else if (msg.status === 'loading') {
      el.replaceChildren(icon('loader-circle', 'spin'), 'טוען את מודל הסיווג');
    } else if (msg.status === 'done') {
      el.replaceChildren(icon('cpu'), 'סיווג חכם פעיל');
      api.reclassify().catch(() => {});
    } else if (msg.status === 'error') {
      // Not fatal: the curated dictionary keeps classifying.
      el.replaceChildren(icon('cpu'), 'סיווג לפי מילון');
      el.title = 'מודל הסיווג לא זמין כרגע (אין רשת?). המילון ממשיך לעבוד, וינסה שוב בהפעלה הבאה.';
    }
  });

  api.on('reclassify_done', (msg) => {
    if (msg.changed) {
      H.toast(`הסיווג עודכן: ${H.songs(msg.changed)} קיבלו נושא מדויק יותר`, { icon: 'cpu' });
      if (['home', 'topics', 'library'].includes(currentView) && views[currentView].refresh) views[currentView].refresh();
    }
  });

  // ------------------------------------------------------------ app updates
  async function checkAppUpdate() {
    const settings = H.settings || {};
    if (settings.auto_update === false) return;
    try {
      const r = await api.checkUpdates(false);
      if (r.online && r.app && r.app.newer) {
        H.$('#update-text').textContent = `גרסה ${r.app.latest} של המנגן זמינה.${r.app.notes ? ` ${r.app.notes}` : ''}`;
        H.$('#update-download').onclick = () => api.openExternal(r.app.url || r.app.page);
        H.$('#update-bar').hidden = false;
      }
    } catch { /* offline: nothing to say */ }
  }
  H.$('#update-dismiss').addEventListener('click', () => { H.$('#update-bar').hidden = true; });

  // ------------------------------------------------------------ core failure
  api.on('backend_failed', (msg) => {
    H.$('#fatal').hidden = false;
    H.$('#fatal-details').textContent = [msg.code !== null && msg.code !== undefined ? `exit code ${msg.code}` : '', msg.stderr || ''].filter(Boolean).join('\n');
  });
  api.on('backend_restarting', () => H.toast('הליבה של המנגן הופעלה מחדש', { icon: 'refresh-cw' }));
  api.on('ready', () => {
    if (!H.$('#fatal').hidden) {
      H.$('#fatal').hidden = true;
      H.go(currentView, lastParams);
    }
  });
  H.$('#fatal-retry').addEventListener('click', async () => {
    H.$('#fatal-details').textContent = 'מנסה שוב…';
    try {
      await api.appInfo();
      H.$('#fatal').hidden = true;
      boot();
    } catch (err) {
      H.$('#fatal-details').textContent = err.message;
    }
  });
  H.$('#fatal-folder').addEventListener('click', async () => {
    const shell = await api.shellInfo();
    api.openFolder(shell.dataDir);
  });

  // ------------------------------------------------------------ keyboard
  document.addEventListener('keydown', (e) => {
    const typing = e.target.closest('input, textarea, select, [contenteditable="true"]');
    if (e.key === '/' && !typing) {
      e.preventDefault();
      if (currentView !== 'home') H.go('home');
      setTimeout(() => views.home.focusAsk(), 0);
      return;
    }
    if (typing) return;
    if (e.code === 'Space' && !e.target.closest('button')) {
      e.preventDefault();
      H.player.toggle();
    } else if (e.ctrlKey && e.key === 'ArrowLeft') {
      H.player.next();
    } else if (e.ctrlKey && e.key === 'ArrowRight') {
      H.player.prev();
    } else if (e.key === 'Escape') {
      H.closeDrawer();
    }
  });

  // ------------------------------------------------------------ boot
  async function boot() {
    let settings = {};
    try {
      settings = await api.getSettings();
    } catch (err) {
      // The core did not answer at all: the fatal screen explains.
      H.$('#fatal').hidden = false;
      H.$('#fatal-details').textContent = err.message;
      return;
    }
    H.settings = settings;
    H.applyTheme(settings.theme);
    H.applyTextSize(settings.text_size);
    api.appInfo().then((info) => { H.appInfo = info; }).catch(() => {});
    H.go('home');
    // Background work, in this order: refresh the library, get the model
    // ready, then look for a newer version.
    H.rescan(false);
    setTimeout(checkAppUpdate, 4000);
  }

  // The luach turns over at midnight even when the app stays open all night.
  function scheduleMidnight() {
    const now = new Date();
    const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 5);
    setTimeout(() => {
      if (currentView === 'home') views.home.refresh();
      scheduleMidnight();
    }, next - now);
  }

  window.addEventListener('DOMContentLoaded', () => {
    boot();
    scheduleMidnight();
  });
})();
