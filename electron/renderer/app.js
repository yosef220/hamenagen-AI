'use strict';

/**
 * Renderer logic. Talks to the Python core only through window.hamenagen
 * (exposed by preload.js). Implements the request flow (§8), playback (§12),
 * the online-fetch flow (§11), settings (§16) and the opening suggestion (§7).
 */

const api = window.hamenagen;

const el = (id) => document.getElementById(id);
const results = el('results');
const statusEl = el('status');
const audio = el('audio');

// Current playback queue.
let queue = [];
let current = -1;
// Active hls.js instance for radio streams (null when not streaming).
let hls = null;

// -- helpers ---------------------------------------------------------------
function setStatus(text) {
  statusEl.textContent = text || '';
}

function fmtTime(sec) {
  if (!sec || Number.isNaN(sec)) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function fileUrl(path) {
  // Prefer the main-process url.pathToFileURL (correct for Windows drive
  // letters, backslashes and Hebrew/spaced names); fall back to a manual build.
  if (api && typeof api.fileUrl === 'function') {
    const u = api.fileUrl(path);
    if (u) return u;
  }
  let s = path.replace(/\\/g, '/');
  let encoded = s.split('/').map(encodeURIComponent).join('/');
  encoded = encoded.replace(/^([A-Za-z])%3A\//, '$1:/'); // restore "C:/"
  return s.startsWith('/') ? 'file://' + encoded : 'file:///' + encoded;
}

// -- rendering results -----------------------------------------------------
function renderResults(tracks) {
  results.innerHTML = '';
  tracks.forEach((t, i) => {
    const li = document.createElement('li');
    li.className = 'result';
    li.dataset.index = String(i);
    li.innerHTML = `
      <span class="idx">${i + 1}</span>
      <div class="meta">
        <div class="title"></div>
        <div class="sub"></div>
      </div>
      ${t.topic ? `<span class="tag"></span>` : ''}`;
    li.querySelector('.title').textContent = t.title || t.filename || 'ללא שם';
    li.querySelector('.sub').textContent = [t.artist, t.album].filter(Boolean).join(' · ');
    if (t.topic) li.querySelector('.tag').textContent = t.topic;
    li.addEventListener('dblclick', () => playAt(i));
    li.addEventListener('click', () => playAt(i));
    results.appendChild(li);
  });
}

function highlightPlaying() {
  [...results.children].forEach((li, i) =>
    li.classList.toggle('playing', i === current)
  );
}

// -- playback --------------------------------------------------------------
function stopHls() {
  if (hls) {
    try { hls.destroy(); } catch { /* ignore */ }
    hls = null;
  }
}

function playAt(index) {
  if (index < 0 || index >= queue.length) return;
  stopHls();
  clearStationHighlight();
  current = index;
  const track = queue[index];
  if (track.is_video) {
    // Video handling would open a video surface; for audio-first v0.1 we still
    // route the file through the same element.
  }
  audio.src = fileUrl(track.path);
  audio.play().catch((e) => setStatus('לא ניתן לנגן את הקובץ: ' + e.message));
  el('np-title').textContent = track.title || track.filename;
  el('np-artist').textContent = track.artist || '';
  el('player-bar').classList.remove('hidden');
  el('btn-play').textContent = '⏸';
  highlightPlaying();
}

function togglePlay() {
  if (audio.paused) { audio.play(); el('btn-play').textContent = '⏸'; }
  else { audio.pause(); el('btn-play').textContent = '▶'; }
}

el('btn-play').addEventListener('click', togglePlay);
el('btn-next').addEventListener('click', () => playAt(current + 1));
el('btn-prev').addEventListener('click', () => playAt(current - 1));
audio.addEventListener('ended', () => playAt(current + 1));
audio.addEventListener('timeupdate', () => {
  el('time-cur').textContent = fmtTime(audio.currentTime);
  el('time-dur').textContent = fmtTime(audio.duration);
  el('seek').value = audio.duration ? String((audio.currentTime / audio.duration) * 100) : '0';
});
el('seek').addEventListener('input', (e) => {
  if (audio.duration) audio.currentTime = (Number(e.target.value) / 100) * audio.duration;
});
el('volume').addEventListener('input', (e) => (audio.volume = Number(e.target.value) / 100));
audio.volume = 0.9;

// -- the request flow (§8) -------------------------------------------------
async function ask(text) {
  if (!text.trim()) return;
  showRadio(false);
  setStatus('מחפש…');
  const res = await api.ask(text);
  if (!res.ok) { setStatus('שגיאה: ' + res.error); return; }
  const data = res.result;
  queue = data.tracks;
  current = -1;
  renderResults(queue);
  updateListActions();
  setStatus(data.note + (data.count ? ` (${data.count})` : ''));
  if (data.found_local && queue.length) {
    playAt(0);
  } else if (!data.found_local) {
    // Nothing local — offer the online fetch flow (§11).
    offerOnline(text);
  }
}

// Show "play in order / shuffle" when there is a list to act on.
function updateListActions() {
  el('list-actions').classList.toggle('hidden', queue.length < 2);
}

function shuffleQueue() {
  for (let i = queue.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [queue[i], queue[j]] = [queue[j], queue[i]];
  }
}

el('btn-play-order').addEventListener('click', () => {
  if (queue.length) playAt(0);
});
el('btn-play-shuffle').addEventListener('click', () => {
  if (!queue.length) return;
  shuffleQueue();
  renderResults(queue);
  playAt(0);
});

el('ask-form').addEventListener('submit', (e) => {
  e.preventDefault();
  ask(el('ask-input').value);
});
document.querySelectorAll('.chip[data-ask]').forEach((c) =>
  c.addEventListener('click', () => ask(c.dataset.ask))
);

// -- online fetch (§11) ----------------------------------------------------
let onlineState = { results: [], selected: 0, query: '' };

async function offerOnline(query) {
  const dialog = el('online-dialog');
  el('online-title').textContent = 'לא מצאתי את השיר';
  el('online-text').textContent = 'האם לחפש ביוטיוב?';
  el('online-results').innerHTML = '';
  dialog.showModal();

  const res = await api.onlineSearch(query, 6);
  if (!res.ok) { el('online-text').textContent = 'שגיאה בחיפוש: ' + res.error; return; }
  const r = res.result;
  onlineState = { results: r.results || [], selected: 0, query };
  el('online-browser').dataset.url = r.search_url || '';

  if (!r.available) {
    el('online-text').textContent =
      'מנוע ההורדה (yt-dlp) אינו מותקן. אפשר לפתוח את החיפוש בדפדפן.';
    return;
  }
  if (!r.results || !r.results.length) {
    el('online-text').textContent = r.message || 'לא נמצאו תוצאות. אפשר לפתוח בדפדפן.';
    return;
  }
  // The system chooses the top result itself (§11): auto-select index 0.
  el('online-text').textContent = 'נבחרה התוצאה המתאימה ביותר. לא לזה התכוונת? בחר אחרת.';
  renderOnline();
}

function renderOnline() {
  const box = el('online-results');
  box.innerHTML = '';
  onlineState.results.forEach((r, i) => {
    const row = document.createElement('div');
    row.className = 'online-item' + (i === onlineState.selected ? ' selected' : '');
    const title = document.createElement('span');
    title.textContent = r.title || r.id;
    const actions = document.createElement('div');
    actions.className = 'oi-actions';
    const playBtn = document.createElement('button');
    playBtn.className = 'btn btn-ghost small';
    playBtn.textContent = 'נגן מיוטיוב';
    playBtn.onclick = () => api.openExternal(r.url);
    const dlBtn = document.createElement('button');
    dlBtn.className = 'btn btn-accent small';
    dlBtn.textContent = 'הורד';
    dlBtn.onclick = () => download(r);
    const pick = document.createElement('button');
    pick.className = 'btn btn-ghost small';
    pick.textContent = 'לא לזה התכוונתי';
    pick.onclick = () => { onlineState.selected = i; renderOnline(); };
    actions.append(playBtn, dlBtn, pick);
    row.append(title, actions);
    box.appendChild(row);
  });
}

async function download(result) {
  const downloadId = result.id || String(Date.now());
  el('online-dialog').close();
  setStatus(`מוריד: ${result.title || ''}…`);

  // Live progress: the backend streams { event:'download_progress', ... }.
  const off = api.onBackendEvent((msg) => {
    if (msg.event !== 'download_progress' || msg.download_id !== downloadId) return;
    if (msg.status === 'downloading') {
      const pct = msg.percent != null ? `${msg.percent}%` : '';
      setStatus(`מוריד: ${result.title || ''} ${pct}`);
    } else if (msg.status === 'postprocessing') {
      setStatus(`ממיר אודיו: ${result.title || ''}…`);
    }
  });

  let res;
  try {
    res = await api.onlineDownload(result, downloadId);
  } finally {
    off();
  }
  if (!res.ok || !res.result.ok) {
    setStatus('ההורדה נכשלה: ' + (res.error || (res.result && res.result.message) || ''));
    return;
  }

  const settings = (await api.getSettings()).result || {};
  const track = res.result.track || {
    path: res.result.path, title: result.title, artist: result.uploader, is_video: false,
  };
  setStatus('ההורדה הושלמה — נוסף למאגר.');
  if (settings.autoplay_after_download && track.path) {
    queue = [track, ...queue];
    playAt(0);
  }
}

el('online-cancel').addEventListener('click', () => el('online-dialog').close());
el('online-browser').addEventListener('click', (e) => {
  const url = e.target.dataset.url;
  if (url) api.openExternal(url);
  el('online-dialog').close();
});

// -- settings (§16) --------------------------------------------------------
async function openSettings() {
  const res = await api.getSettings();
  const s = res.result || {};
  el('set-builtin').checked = !!s.use_builtin_player;
  el('set-video').checked = !!s.include_video;
  el('set-autoupdate').checked = !!s.auto_update;
  el('set-autoplay').checked = !!s.autoplay_after_download;
  el('set-embeddings').checked = !!s.use_embeddings;
  el('set-roots').value = (s.scan_roots || []).join('\n');
  el('settings-dialog').showModal();
  refreshClassifierStatus();
}

async function refreshClassifierStatus() {
  const res = await api.classifierStatus();
  const box = el('classifier-status');
  if (!res.ok) { box.textContent = ''; return; }
  const st = res.result || {};
  if (!st.enabled) {
    box.textContent = 'סיווג חכם מכובה — פעיל המילון בלבד.';
  } else if (st.available) {
    box.textContent = `מודל הסיווג פעיל: ${st.model}`;
  } else {
    box.textContent = `המודל אינו טעון עדיין (${st.model}). ירד בפעם הראשונה שבה יידרש, או דרך חבילת האופליין.`;
  }
}

el('btn-reclassify').addEventListener('click', async () => {
  el('classifier-status').textContent = 'מסווג מחדש…';
  const res = await api.reclassify();
  if (res.ok) {
    el('classifier-status').textContent = `הסתיים: ${res.result.changed} שירים שונו מתוך ${res.result.total}.`;
  } else {
    el('classifier-status').textContent = 'שגיאה בסיווג מחדש: ' + res.error;
  }
});

el('settings-form').addEventListener('submit', async (e) => {
  if (e.submitter && e.submitter.value === 'save') {
    const roots = el('set-roots').value.split('\n').map((r) => r.trim()).filter(Boolean);
    await api.updateSettings({
      use_builtin_player: el('set-builtin').checked,
      include_video: el('set-video').checked,
      auto_update: el('set-autoupdate').checked,
      autoplay_after_download: el('set-autoplay').checked,
      use_embeddings: el('set-embeddings').checked,
      scan_roots: roots,
    });
    setStatus('ההגדרות נשמרו.');
  }
});

// -- updates + offline pack (spec §14, §6.2) -------------------------------
el('btn-check-updates').addEventListener('click', async () => {
  const box = el('updates-status');
  box.textContent = 'בודק עדכונים…';
  checkAppUpdate(true);  // app version (front-end); yt-dlp/lexicon below
  const res = await api.checkUpdates();
  if (!res.ok) { box.textContent = 'שגיאה: ' + res.error; return; }
  const data = res.result;
  if (!data.online) {
    box.textContent = 'לא ניתן לבדוק עדכונים כעת (אין רשת או לא הוגדר שרת עדכונים).';
    return;
  }
  if (!data.updates.length) { box.textContent = 'הכול מעודכן ✓'; return; }
  const names = data.updates.map((u) => `${u.component} → ${u.latest}`).join(', ');
  box.textContent = `עדכונים זמינים: ${names}`;
  // Apply the auto-updatable ones (e.g. yt-dlp, lexicon).
  for (const u of data.updates.filter((x) => x.action === 'auto')) {
    box.textContent = `מעדכן ${u.component}…`;
    const ap = await api.applyUpdate(u.component, u.url, u.latest);
    box.textContent = ap.ok && ap.result.ok
      ? `${u.component} עודכן ✓`
      : `עדכון ${u.component} נכשל: ${(ap.result && ap.result.message) || ap.error}`;
  }
});

el('btn-install-pack').addEventListener('click', async () => {
  const box = el('updates-status');
  box.textContent = 'מחפש חבילת אופליין…';
  const res = await api.installOfflinePack(null);
  if (!res.ok) { box.textContent = 'שגיאה: ' + res.error; return; }
  const r = res.result;
  box.textContent = r.count
    ? `הותקנו ${r.count} חבילות אופליין ✓`
    : 'לא נמצאה חבילת אופליין חדשה בתיקיית התוכנה.';
});

el('nav-settings').addEventListener('click', openSettings);
// Background scan — never blocks the UI (spec §9). Runs on startup and on the
// manual button; results/index refresh when the "scan_done" event arrives.
let scanning = false;

async function startBackgroundScan(announce) {
  if (scanning) return;
  const res = await api.rescanAsync();
  if (res.ok && res.result.started) {
    scanning = true;
    if (announce) setStatus('סורק את המאגר ברקע… אפשר להמשיך להשתמש');
  }
}

api.onBackendEvent((msg) => {
  if (msg.event === 'scan_done') {
    scanning = false;
    if (msg.error) { setStatus('שגיאה בסריקה: ' + msg.error); return; }
    setStatus(`המאגר עודכן: ${msg.total} שירים (נוספו ${msg.added}).`);
    return;
  }
  if (msg.event === 'model_install') {
    if (msg.status === 'downloading') {
      setStatus('מתקין את מודל ה-AI ברקע (הורדה חד-פעמית)… אפשר להמשיך להשתמש');
    } else if (msg.status === 'done') {
      setStatus('מודל ה-AI הותקן ✓ מסווג מחדש את המאגר…');
      api.reclassify().then(() => setStatus('מודל ה-AI מוכן — הסיווג עודכן ✓'));
    } else if (msg.status === 'error') {
      // Non-fatal: the curated dictionary keeps working.
      setStatus('לא ניתן להתקין את מודל ה-AI כעת (המילון ממשיך לעבוד).');
    }
  }
});

// First-run: if the AI model isn't installed yet, download it in the
// background when online (spec §6.1). The curated dictionary works meanwhile.
async function ensureModelInstalled() {
  const res = await api.classifierStatus();
  if (!res.ok) return;
  const st = res.result || {};
  if (st.enabled && !st.available) {
    api.installModelAsync();
  }
}

el('nav-rescan').addEventListener('click', () => startBackgroundScan(true));

// -- opening suggestion (§7) ----------------------------------------------
async function loadSuggestion() {
  const res = await api.openingSuggestion();
  if (!res.ok || !res.result) return;
  const s = res.result;
  el('suggestion-date').textContent = s.hebrew_date;
  el('suggestion-label').textContent = `היום ${s.label} — לשמוע שירים מתאימים?`;
  el('suggestion').classList.remove('hidden');
  el('suggestion-play').onclick = () => ask(`תשמיע לי שירים של ${s.topic}`);
}
el('suggestion-dismiss').addEventListener('click', () =>
  el('suggestion').classList.add('hidden')
);

// -- radio (spec §13) ------------------------------------------------------
function showRadio(show) {
  el('radio-panel').classList.toggle('hidden', !show);
  el('results').classList.toggle('hidden', show);
  if (show) el('list-actions').classList.add('hidden');
}

function clearStationHighlight() {
  document.querySelectorAll('.station.playing').forEach((s) => s.classList.remove('playing'));
}

async function loadRadio() {
  showRadio(true);
  el('radio-status').textContent = 'טוען ערוצים…';
  el('radio-grid').innerHTML = '';
  const res = await api.radioList(true);
  if (!res.ok) { el('radio-status').textContent = 'שגיאה: ' + res.error; return; }
  const data = res.result;
  el('radio-status').textContent = data.online
    ? `מחובר — ${data.count} ערוצים`
    : `מצב לא-מקוון — מציג רשימה שמורה (${data.count})`;
  renderStations(data.stations);
}

function renderStations(stations) {
  const grid = el('radio-grid');
  grid.innerHTML = '';
  stations.forEach((st) => {
    const card = document.createElement('button');
    card.className = 'station';
    card.type = 'button';
    const img = st.image_url
      ? `<img src="${st.image_url}" alt="" loading="lazy" onerror="this.style.visibility='hidden'" />`
      : '<div class="st-icon">📻</div>';
    card.innerHTML = `
      ${img}
      <div class="st-meta">
        <div class="st-title"></div>
        <div class="st-sub"></div>
      </div>
      <span class="st-play">▶</span>`;
    card.querySelector('.st-title').textContent = st.title;
    card.querySelector('.st-sub').textContent = st.now_playing || st.description || '';
    card.addEventListener('click', () => {
      clearStationHighlight();
      card.classList.add('playing');
      playStream(st);
    });
    grid.appendChild(card);
  });
}

function playStream(station) {
  stopHls();
  current = -1;
  const url = station.url;
  const isHls = /\.m3u8(\?|$)/i.test(url);
  if (isHls && window.Hls && window.Hls.isSupported()) {
    hls = new window.Hls();
    hls.loadSource(url);
    hls.attachMedia(audio);
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => audio.play().catch(() => {}));
    hls.on(window.Hls.Events.ERROR, (_e, data) => {
      if (data && data.fatal) setStatus('שגיאת שידור: ' + station.title);
    });
  } else {
    // Non-HLS stream, or native HLS support (rare on desktop Chromium).
    audio.src = url;
    audio.play().catch((e) => setStatus('לא ניתן לנגן את הערוץ: ' + e.message));
  }
  el('np-title').textContent = station.title;
  el('np-artist').textContent = station.now_playing || 'רדיו חי';
  el('player-bar').classList.remove('hidden');
  el('btn-play').textContent = '⏸';
}

el('nav-radio').addEventListener('click', loadRadio);

// -- app self-update check (spec §14) --------------------------------------
// Compares this build's SHA against a manifest published beside the release.
// If they differ, a newer build exists — offer a one-click download.
const UPDATE_MANIFEST_URL =
  'https://github.com/yosef220/hamenagen-AI/releases/download/portable-latest/update.json';

async function checkAppUpdate(manual) {
  const cur = (window.__BUILD__ || {}).build || 'dev';
  try {
    const r = await fetch(UPDATE_MANIFEST_URL, { cache: 'no-store' });
    if (!r.ok) throw new Error('manifest ' + r.status);
    const m = await r.json();
    if (m.build && cur !== 'dev' && m.build !== cur) {
      el('update-text').textContent =
        'גרסה חדשה של המנגן זמינה — כדאי לעדכן.' + (m.notes ? ' ' + m.notes : '');
      el('update-download').onclick = () => api.openExternal(m.zip_url || (window.__BUILD__).zip_url);
      el('update-bar').classList.remove('hidden');
    } else if (manual) {
      setStatus('התוכנה מעודכנת ✓');
    }
  } catch {
    if (manual) setStatus('לא ניתן לבדוק עדכוני אפליקציה כעת (אין רשת).');
  }
}

el('update-dismiss').addEventListener('click', () =>
  el('update-bar').classList.add('hidden')
);

// -- theme (light / dark) --------------------------------------------------
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = el('nav-theme');
  if (btn) btn.textContent = theme === 'light' ? '☀️ בהיר' : '🌙 כהה';
  try { localStorage.setItem('theme', theme); } catch { /* ignore */ }
}

function initTheme() {
  let theme = 'dark';
  try { theme = localStorage.getItem('theme') || 'dark'; } catch { /* ignore */ }
  applyTheme(theme === 'light' ? 'light' : 'dark');
}

el('nav-theme').addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  applyTheme(current === 'light' ? 'dark' : 'light');
});

// -- boot ------------------------------------------------------------------
window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  loadSuggestion();
  el('ask-input').focus();
  // Auto-scan the library in the background on every launch (spec §9), so the
  // catalogue stays fresh without the user ever pressing "scan".
  startBackgroundScan(false);
  // First-run: install the AI model in the background when online (spec §6.1).
  ensureModelInstalled();
  // Notify if a newer app build is available (one-click download).
  checkAppUpdate(false);
});
