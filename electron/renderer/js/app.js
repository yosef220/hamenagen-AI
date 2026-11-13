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
  function switchTo(name) {
    // Leaving the Google search: its page goes away with it (main.js).
    if (currentView === 'websearch' && name !== 'websearch') api.searchHide();
    currentView = name;
    for (const section of H.$$('.view')) section.hidden = section.dataset.view !== name;
    H.$('#main').classList.toggle('is-websearch', name === 'websearch');
    const navName = name === 'results' || name === 'websearch' ? null : name;
    for (const item of H.$$('.nav-item')) {
      if (item.dataset.view === navName) item.setAttribute('aria-current', 'page');
      else item.removeAttribute('aria-current');
    }
  }

  H.go = function go(name, params = {}) {
    if (!views[name]) return;
    switchTo(name);
    lastParams = params;
    H.$('#main').scrollTop = 0;
    views[name].show(params);
  };

  /** Back to a view as it was left, without drawing it again. */
  H.reveal = function reveal(name) {
    if (!views[name]) return;
    switchTo(name);
  };
  H.currentView = () => currentView;

  for (const item of H.$$('.nav-item')) item.addEventListener('click', () => H.go(item.dataset.view));

  /** A typed request: understand it and start playing (spec §8). */
  H.ask = function ask(text, opts = {}) {
    const clean = String(text || '').trim();
    if (!clean) return;
    H.go('results', { text: clean, autoplay: true, spoken: !!opts.spoken });
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

  H.refreshRail = () => refreshRail();
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
    const choice = (H.settings && H.settings.model_download) || 'ask';
    // In the offline editions the model is already on the computer: loading reads it.
    if (st.bundled || st.cached || choice === 'yes') { api.installModel().catch(() => {}); return; }
    if (choice === 'no') return;
    offerModel();
  }

  // 1.5.1: nothing big is downloaded without asking.
  function offerModel() {
    if (H.$('#model-offer')) return;
    const close = () => bar.remove();
    const answer = async (value) => {
      close();
      try { H.settings = await api.updateSettings({ model_download: value }); } catch { /* kept for this run */ }
      if (value === 'yes') api.installModel().catch(() => {});
    };
    const bar = h('div', { class: 'update-bar', id: 'model-offer', role: 'region', 'aria-label': 'מודל הסיווג' },
      icon('cpu'),
      h('span', { class: 'model-offer-text' },
        'כדי לזהות נושא של שיר גם כשאין לו מילת מפתח בשם, המנגן יכול להוריד מודל שפה קטן שעובד במחשב (כ-450MB, פעם אחת). ',
        'בלי המודל הסיווג ממשיך לפי המילון ואינדקס השירים.'),
      h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => answer('yes') }, 'להוריד'),
      h('button', { class: 'btn btn-quiet', type: 'button', onclick: close }, 'לא עכשיו'),
      h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => answer('no') }, 'לא לשאול שוב'));
    const main = H.$('#main');
    main.insertBefore(bar, main.firstChild);
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

  // ------------------------------------------------------------ listening for vocal songs
  api.on('vocal_progress', (msg) => {
    const el = H.$('#rail-vocal');
    el.replaceChildren(icon('ear'), `מקשיב לשירים · ${H.n(msg.done)} מתוך ${H.n(msg.total)}`);
    el.title = 'המנגן מזהה שירים ווקאליים (בלי כלי נגינה). רץ ברקע ובלי אינטרנט.';
  });

  api.on('vocal_done', (msg) => {
    const el = H.$('#rail-vocal');
    el.replaceChildren();
    if (msg.error || !msg.ok) return;
    if (msg.found) {
      H.toast(`המנגן הקשיב לשירים וזיהה ${H.songs(msg.found)} בלי כלי נגינה`, {
        icon: 'ear', ms: 9000, action: { label: 'לבדוק', fn: () => H.openTopic('ווקאלי') },
      });
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
        // After a failed swap, the full download rather than the same update.
        if (H.updateFailed && r.app.smart) r.app.smart.possible = false;
        H.showAppUpdate(r.app);
      }
    } catch { /* offline: nothing to say */ }
  }

  // ------------------------------------------------------------ the smart update
  // Only the parts of the app that changed are downloaded (the AI model, Python
  // and Electron usually stay); then the app closes for a moment and comes back.
  const MB = (n) => `${Math.max(0.1, n / 1048576).toFixed(n > 10 * 1048576 ? 0 : 1)}MB`;
  let updating = false;

  H.showAppUpdate = function showAppUpdate(info) {
    const text = H.$('#update-text');
    const button = H.$('#update-download');
    const smart = info.smart || {};
    button.disabled = false;
    if (smart.possible) {
      const saved = smart.full > smart.download * 1.5 ? ` (במקום ${smart.full_text})` : '';
      text.textContent = `גרסה ${info.latest} זמינה: עדכון של ${smart.download_text}${saved}.${info.notes ? ` ${info.notes}` : ''}`;
      button.textContent = 'לעדכן עכשיו';
      button.onclick = () => H.startAppUpdate(info);
    } else {
      text.textContent = `גרסה ${info.latest} של המנגן זמינה.${info.notes ? ` ${info.notes}` : ''}`;
      button.textContent = 'להורדה';
      button.onclick = () => api.openExternal(info.url || info.page);
    }
    H.$('#update-bar').hidden = false;
  };

  H.startAppUpdate = async function startAppUpdate(info) {
    if (updating) return;
    updating = true;
    const text = H.$('#update-text');
    const button = H.$('#update-download');
    H.$('#update-bar').hidden = false;
    button.disabled = true;
    text.textContent = 'מוריד את החלקים שהשתנו…';
    const off = [];
    const finish = () => { off.forEach((f) => f()); updating = false; };
    off.push(api.on('app_update_progress', (p) => {
      if (p.status === 'downloading' && p.total) {
        text.textContent = `מוריד את העדכון… ${Math.floor((100 * p.done) / p.total)}% (${MB(p.done)} מתוך ${MB(p.total)})`;
      } else if (p.status === 'checking') {
        text.textContent = 'בודק שהקבצים שלמים…';
      }
    }));
    off.push(api.on('app_update_done', (res) => {
      finish();
      if (res && res.ok) {
        text.textContent = `גרסה ${res.version || info.latest} מוכנה. המנגן ייסגר לרגע ויחזור מעודכן.`;
        button.textContent = 'להפעיל מחדש ולעדכן';
        button.disabled = false;
        button.onclick = async () => {
          button.disabled = true;
          const r = await api.applyAppUpdate(res.plan).catch((err) => ({ ok: false, message: err.message }));
          if (!r.ok) {
            text.textContent = `העדכון לא הופעל: ${r.message}`;
            button.textContent = 'להורדה מלאה';
            button.disabled = false;
            button.onclick = () => api.openExternal(info.url || info.page);
          }
        };
      } else {
        text.textContent = `העדכון לא הצליח${res && res.message ? `: ${res.message}` : ''}. אפשר להוריד את הגרסה המלאה.`;
        button.textContent = 'להורדה מלאה';
        button.disabled = false;
        button.onclick = () => api.openExternal(info.url || info.page);
      }
    }));
    try {
      const started = await api.appUpdateDownload();
      if (!started.started) throw new Error(started.reason === 'already running' ? 'כבר מוריד' : (started.reason || ''));
    } catch (err) {
      finish();
      text.textContent = `העדכון לא התחיל: ${err.message}`;
      button.disabled = false;
    }
  };

  /** After an update the app comes back: say how it went (once). */
  async function reportAppUpdate() {
    try {
      const { result } = await api.appUpdateResult();
      if (!result) return;
      if (result.ok) {
        H.toast(`המנגן עודכן לגרסה ${result.version}`, { icon: 'circle-check' });
        return;
      }
      // It did not work: say so where it stays, and offer the full file
      // (the same small update would most likely fail the same way).
      if (result.log) console.warn(`smart update log:\n${result.log}`);
      H.$('#update-text').textContent = `העדכון ל-${result.version || 'הגרסה החדשה'} לא הושלם, והגרסה הקודמת נשארה ועובדת. `
        + 'אפשר להוריד את הגרסה המלאה ולהתקין מעל — הספרייה וההגדרות נשמרות.';
      const button = H.$('#update-download');
      button.disabled = false;
      button.textContent = 'להורדה מלאה';
      button.onclick = () => api.openExternal('https://github.com/yosef220/hamenagen-AI/releases/latest');
      H.$('#update-bar').hidden = false;
      H.updateFailed = true;
    } catch { /* nothing to report */ }
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
    if (e.ctrlKey && !e.shiftKey && !e.altKey && e.code === 'KeyM' && H.voice) {
      e.preventDefault();
      if (H.voice.state === 'idle' && currentView !== 'home') H.go('home');
      H.voice.toggle();
      return;
    }
    if (e.key === 'Escape' && H.voice && H.voice.state === 'listening') {
      H.voice.cancel();
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
    H.player.setCrossfade(settings.crossfade_seconds || 0);
    H.player.setSoundOptions({ normalize: settings.normalize_volume !== false, skipSilence: settings.skip_silence !== false });
    H.applyTheme(settings.theme);
    H.applyTextSize(settings.text_size);
    api.appInfo().then((info) => { H.appInfo = info; }).catch(() => {});
    H.go('home');
    // Background work, in this order: refresh the library, get the model
    // ready, then look for a newer version.
    H.rescan(false);
    setTimeout(checkAppUpdate, 4000);
    setTimeout(reportAppUpdate, 1500);
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
