'use strict';

/**
 * Electron main process (spec §6, §15).
 *
 * Owns the application window and everything that needs the operating
 * system: which edition this is and where its data lives, the single-instance
 * lock, the window's size and theme, folder pickers, the taskbar's player
 * buttons, and the desktop shortcut of the ZIP editions. Requests from the
 * window go to the Python core through {@link BackendBridge}.
 */

const {
  app, BrowserWindow, Menu, WebContentsView, clipboard, dialog, ipcMain, nativeImage, nativeTheme, net, powerMonitor,
  protocol, screen, session, shell,
} = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { BackendBridge } = require('./backend_bridge');
const { NativeSearch } = require('./searchwin');

const pkg = require('../package.json');

const APP_ID = 'org.community.hamenagen';

// --- edition and folders ----------------------------------------------------
// "portable" and "offline" (one EXE that opens into a folder; offline has the
// AI model inside), "setup" and "setup-offline" (installers).
const EDITION = app.isPackaged ? (pkg.hamenagenEdition || 'portable') : 'dev';
const EDITION_LABELS = {
  portable: 'גרסה ניידת',
  offline: 'גרסה ניידת עם המודל (אופליין)',
  setup: 'גרסה מותקנת',
  'setup-offline': 'גרסה מותקנת עם המודל (אופליין)',
  dev: 'גרסת פיתוח',
};
const INSTALLED = EDITION === 'setup' || EDITION === 'setup-offline';

function isWritable(dir) {
  try {
    fs.mkdirSync(dir, { recursive: true });
    const probe = path.join(dir, '.writetest');
    fs.writeFileSync(probe, 'ok');
    fs.unlinkSync(probe);
    return true;
  } catch {
    return false;
  }
}

/** Where the library, settings and favorites live (see the spec's table). */
function resolveDataDir() {
  if (process.env.HAMENAGEN_DATA_DIR) return process.env.HAMENAGEN_DATA_DIR;
  if (!app.isPackaged) return path.join(__dirname, '..', 'data');
  const appData = path.join(app.getPath('appData'), 'Hamenagen');
  if (INSTALLED) return appData;
  // The ZIP editions keep their data beside the program, so the folder can be
  // carried to another computer — unless that place is read-only.
  const beside = path.join(path.dirname(process.execPath), 'data');
  return isWritable(beside) ? beside : appData;
}

const DATA_DIR = resolveDataDir();
fs.mkdirSync(DATA_DIR, { recursive: true });
// Chromium's own storage goes in a sub-folder with an ASCII path.
app.setPath('userData', path.join(DATA_DIR, 'app'));

function bundledResource(name) {
  const dir = path.join(process.resourcesPath || '', name);
  return app.isPackaged && fs.existsSync(dir) ? dir : '';
}

const bridge = new BackendBridge({
  env: {
    HAMENAGEN_DATA_DIR: DATA_DIR,
    HAMENAGEN_MODELS_DIR: bundledResource('models'),
    HAMENAGEN_AUDIO_MODELS_DIR: bundledResource('audio-models'),
    HAMENAGEN_VOICE_MODELS_DIR: bundledResource('voice-models'),
    HAMENAGEN_FFMPEG_DIR: bundledResource('ffmpeg'),
    HAMENAGEN_JS_DIR: bundledResource('js'),
    HAMENAGEN_MUSIC_DIR: safePath('music'),
    HAMENAGEN_EDITION: EDITION,
  },
  logFile: path.join(DATA_DIR, 'logs', 'core.log'),
});

function safePath(name) {
  try { return app.getPath(name); } catch { return ''; }
}

// --- album covers ------------------------------------------------------------------
// The core keeps each cover once, by its content, in data/covers/src. The
// window asks for cover://<key>; the first time, a small copy (320 px JPEG)
// is made here with nativeImage and the original is dropped, so a library of
// a thousand albums stays a few MB.
const COVERS_DIR = path.join(DATA_DIR, 'covers');
const COVER_SIZE = 320;
const COVER_KEY = /^[0-9a-f]{12,40}$/;

protocol.registerSchemesAsPrivileged([
  { scheme: 'cover', privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

function coverSource(key) {
  const dir = path.join(COVERS_DIR, 'src');
  for (const ext of ['jpg', 'png', 'jpeg', 'webp', 'gif', 'bmp']) {
    const file = path.join(dir, `${key}.${ext}`);
    if (fs.existsSync(file)) return file;
  }
  return '';
}

/** The file to show for a cover: the small copy, made now if needed. */
function coverFile(key) {
  const small = path.join(COVERS_DIR, `${key}.jpg`);
  if (fs.existsSync(small)) return small;
  const src = coverSource(key);
  if (!src) return '';
  if (!/\.(jpe?g|png)$/i.test(src)) return src; // shown as it is (Chromium reads it)
  try {
    const img = nativeImage.createFromPath(src);
    if (img.isEmpty()) return src;
    const { width, height } = img.getSize();
    const scale = Math.min(1, COVER_SIZE / Math.max(width, height));
    const out = scale < 1
      ? img.resize({ width: Math.round(width * scale), height: Math.round(height * scale), quality: 'good' })
      : img;
    const tmp = `${small}.part`;
    fs.writeFileSync(tmp, out.toJPEG(85));
    fs.renameSync(tmp, small);
    fs.unlinkSync(src);
    return small;
  } catch {
    return src;
  }
}

let compacting = false;
/** After a scan or a download: make the small copies of new covers in the
 * background, a few at a time, so the folder does not keep originals. */
function compactCovers() {
  if (compacting) return;
  let names = [];
  try { names = fs.readdirSync(path.join(COVERS_DIR, 'src')); } catch { return; }
  const keys = [...new Set(names.map((n) => n.split('.')[0]).filter((k) => COVER_KEY.test(k)))];
  if (!keys.length) return;
  compacting = true;
  const step = () => {
    for (let i = 0; i < 8 && keys.length; i += 1) coverFile(keys.shift());
    if (keys.length) setTimeout(step, 30);
    else compacting = false;
  };
  setTimeout(step, 1500);
}

// --- one window only ------------------------------------------------------------
if (!app.requestSingleInstanceLock()) {
  app.quit();
}

let mainWindow = null;

app.on('second-instance', () => {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
});

// --- window geometry, remembered between runs ------------------------------------
const BOUNDS_FILE = path.join(DATA_DIR, 'window.json');

function loadBounds() {
  try {
    const b = JSON.parse(fs.readFileSync(BOUNDS_FILE, 'utf8'));
    const visible = screen.getAllDisplays().some((d) => {
      const a = d.workArea;
      return b.x < a.x + a.width - 80 && b.x + b.width > a.x + 80 && b.y >= a.y - 10 && b.y < a.y + a.height - 80;
    });
    return visible ? b : null;
  } catch {
    return null;
  }
}

function saveBounds() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  try {
    const b = mainWindow.getNormalBounds();
    fs.writeFileSync(BOUNDS_FILE, JSON.stringify({ ...b, maximized: mainWindow.isMaximized() }));
  } catch { /* not important */ }
}

// --- theme ---------------------------------------------------------------------
const THEME_BG = { light: '#F5F7FA', dark: '#0B1322' };

function readSavedTheme() {
  try {
    const s = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'settings.json'), 'utf8'));
    return ['light', 'dark', 'system'].includes(s.theme) ? s.theme : 'system';
  } catch {
    return 'system';
  }
}

// --- taskbar player buttons (Windows) ------------------------------------------
const ICON_DIR = path.join(__dirname, '..', 'assets');
let playerState = { playing: false, hasTrack: false };

function thumbIcon(name) {
  return nativeImage.createFromPath(path.join(ICON_DIR, 'thumbar', `${name}.png`));
}

function updateThumbar() {
  if (process.platform !== 'win32' || !mainWindow || mainWindow.isDestroyed()) return;
  if (!playerState.hasTrack) {
    mainWindow.setThumbarButtons([]);
    return;
  }
  const send = (action) => () => mainWindow.webContents.send('player:command', action);
  mainWindow.setThumbarButtons([
    { tooltip: 'הקודם', icon: thumbIcon('previous'), click: send('previous') },
    playerState.playing
      ? { tooltip: 'השהה', icon: thumbIcon('pause'), click: send('toggle') }
      : { tooltip: 'נגן', icon: thumbIcon('play'), click: send('toggle') },
    { tooltip: 'הבא', icon: thumbIcon('next'), click: send('next') },
  ]);
}

// --- the microphone (requests by voice, 1.4) ----------------------------------------
// Only the app's own page (file://) may use it, and only for sound: the
// recording stays in the window and goes to the core, which recognizes the
// speech on this computer. Every other permission stays refused.
function isOwnPage(url) {
  return typeof url === 'string' && url.startsWith('file://');
}
function allowMicrophone(ses) {
  ses.setPermissionRequestHandler((wc, permission, done, details) => {
    const audioOnly = permission === 'media'
      && Array.isArray(details.mediaTypes) && details.mediaTypes.length > 0
      && details.mediaTypes.every((t) => t === 'audio');
    done(audioOnly && isOwnPage(details.requestingUrl || (wc && wc.getURL())));
  });
  ses.setPermissionCheckHandler((_wc, permission, origin, details) => {
    if (permission !== 'media') return false;
    if (details && details.mediaType && details.mediaType !== 'audio') return false;
    return isOwnPage((details && details.requestingUrl) || origin);
  });
}

// --- the window ------------------------------------------------------------------
function createWindow() {
  const saved = loadBounds();
  nativeTheme.themeSource = readSavedTheme();
  mainWindow = new BrowserWindow({
    width: saved ? saved.width : 1280,
    height: saved ? saved.height : 820,
    x: saved ? saved.x : undefined,
    y: saved ? saved.y : undefined,
    minWidth: 960,
    minHeight: 640,
    show: false,
    title: 'המנגן',
    icon: path.join(ICON_DIR, 'icon.png'),
    backgroundColor: nativeTheme.shouldUseDarkColors ? THEME_BG.dark : THEME_BG.light,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
      backgroundThrottling: false, // keep the player's clock running when hidden
    },
  });
  allowMicrophone(mainWindow.webContents.session);
  Menu.setApplicationMenu(null);
  mainWindow.removeMenu();
  if (saved && saved.maximized) mainWindow.maximize();

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.once('ready-to-show', () => mainWindow.show());
  for (const evt of ['resize', 'move', 'maximize', 'unmaximize']) mainWindow.on(evt, debounce(saveBounds, 500));
  mainWindow.on('close', saveBounds);
  mainWindow.on('closed', () => {
    mainWindow = null;
    // 1.7.3: the hidden search window must not keep the app running.
    if (linksWindow && !linksWindow.isDestroyed()) linksWindow.destroy();
  });
  watchFront();

  // Links never navigate the app window; web pages open in the browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith('file://')) {
      e.preventDefault();
      if (/^https?:\/\//.test(url)) shell.openExternal(url);
    }
  });
}

function debounce(fn, ms) {
  let t = null;
  return () => { clearTimeout(t); t = setTimeout(fn, ms); };
}

// Backend events (progress, ready …) go to the window.
bridge.onEvent((msg) => {
  if (msg && (msg.event === 'scan_done' || msg.event === 'download_batch_done')) compactCovers();
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('backend:event', msg);
});

// --- IPC: requests to the Python core ------------------------------------------------
const BACKEND_METHODS = new Set([
  'ping', 'app_info', 'today', 'opening_suggestion', 'shabbat_status',
  'handle_request', 'playlist', 'set_favorite', 'record_play', 'track_lyrics',
  'library_overview', 'list_tracks', 'topics', 'rescan_async',
  'classifier_status', 'install_model_async', 'reclassify_async',
  'get_settings', 'update_settings',
  'radio_list', 'check_updates', 'apply_update', 'offline_pack_status', 'install_offline_pack',
  'online_available', 'online_search', 'online_web_search', 'online_download', 'online_link',
  'download_batch_async', 'stop_downloads', 'lookup_details', 'apply_details',
  'set_track_topic', 'set_track_vocal', 'confirm_vocal',
  'playlists', 'playlist_get', 'playlist_create', 'playlist_rename', 'playlist_delete', 'playlist_add',
  'playlist_set_order', 'track_copies', 'online_set', 'listen_prepare',
  'app_update_download_async', 'app_update_cancel', 'app_update_result',
  'complete_details_async', 'stop_complete_details',
  'vocal_status', 'vocal_review', 'analyze_vocal_async', 'stop_vocal',
  'set_track_speech', 'set_track_disliked', 'station', 'artist_groups', 'set_artist_choice',
  'voice_status', 'voice_prepare', 'voice_recognize', 'install_voice_async',
  'write_tags', 'write_all_tags_async', 'export_drives', 'export_plan', 'export_run_async', 'export_stop',
  'ringtone_info', 'make_ringtone', 'import_singers', 'clear_singers', 'singers_status',
  'singer_from_links',
  'singer_songs', 'follow_singer', 'followed_new', 'dismiss_new',
  'diagnostics_report',
  'set_mood_mark',
  'name_suggestions', 'apply_name_fixes', 'undo_name_fixes',
  'playlist_import', 'playlist_export',
  'save_position', 'record_skip',
]);

ipcMain.handle('backend', async (_evt, method, params) => {
  if (!BACKEND_METHODS.has(method)) return { ok: false, error: `unknown method: ${method}` };
  try {
    return { ok: true, result: await bridge.call(method, params || {}) };
  } catch (err) {
    return { ok: false, error: String(err && err.message ? err.message : err) };
  }
});

// --- IPC: things only the main process can do ----------------------------------------------
ipcMain.handle('app:info', () => ({
  version: app.getVersion(),
  edition: EDITION,
  editionLabel: EDITION_LABELS[EDITION] || EDITION,
  dataDir: DATA_DIR,
  packaged: app.isPackaged,
  platform: process.platform,
  dark: nativeTheme.shouldUseDarkColors,
}));

ipcMain.handle('app:setTheme', (_evt, theme) => {
  nativeTheme.themeSource = ['light', 'dark', 'system'].includes(theme) ? theme : 'system';
  if (mainWindow) mainWindow.setBackgroundColor(nativeTheme.shouldUseDarkColors ? THEME_BG.dark : THEME_BG.light);
  return { dark: nativeTheme.shouldUseDarkColors };
});

nativeTheme.on('updated', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('app:theme', { dark: nativeTheme.shouldUseDarkColors });
  }
});

ipcMain.handle('app:openExternal', async (_evt, url) => {
  if (typeof url === 'string' && /^https?:\/\//.test(url)) {
    await shell.openExternal(url);
    return { ok: true };
  }
  return { ok: false, error: 'invalid url' };
});

// --- the smart update: swap the downloaded parts in after the app closes ------------------
// The core downloaded and checked the changed parts (smart_update.py) and wrote
// a plan in data/update. A small PowerShell script waits for the app to exit,
// swaps the parts (putting the old ones back if anything fails) and starts
// the app again; the outcome waits in data/update/result.json.
// Every step of the smart update, to data/update/app.log (the script adds
// its own apply.log): when an update does not finish, these say where.
function updateLog(text) {
  try {
    const dir = path.join(DATA_DIR, 'update');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, 'app.log'), `${new Date().toISOString()} ${text}\n`);
  } catch { /* best effort */ }
}

async function applyUpdatePlan(planPath) {
  for (const f of ['app.log', 'apply.log']) {
    try { fs.rmSync(path.join(DATA_DIR, 'update', f), { force: true }); } catch { /* ignore */ }
  }
  updateLog(`apply requested: ${planPath}`);
  if (process.platform !== 'win32' || !app.isPackaged) {
    return { ok: false, message: 'העדכון החכם פועל רק בתוכנה עצמה ב-Windows.' };
  }
  const work = path.join(DATA_DIR, 'update');
  const plan = typeof planPath === 'string' ? path.resolve(planPath) : '';
  if (!plan || path.dirname(plan) !== path.resolve(work) || !fs.existsSync(plan)) {
    updateLog(`no plan: ${plan} (work ${path.resolve(work)})`);
    return { ok: false, message: 'אין עדכון מוכן.' };
  }
  const script = path.join(work, 'apply.ps1');
  try {
    fs.writeFileSync(script, fs.readFileSync(path.join(__dirname, 'update-apply.ps1')));
  } catch (err) {
    return { ok: false, message: String(err && err.message ? err.message : err) };
  }
  // The core first, and wait until it is really gone: it runs Python from
  // the program's folder, and in 1.4.0 it outlived the window (its kill was
  // timed after the app had already quit), so the swap waited and rolled back.
  await bridge.stopAndWait(2000);
  updateLog('core stopped');
  try {
    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    const powershell = path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    const cmd = path.join(systemRoot, 'System32', 'cmd.exe');
    // Through cmd's "start": a detached process gets no console, and Windows
    // PowerShell exits at once without one (1.4.0/1.4.1: the app closed and
    // the script never ran). "start /min" gives it a console of its own,
    // minimised and then hidden, outside the app's process tree.
    const q = (x) => `"${x}"`;
    const line = ['start', '""', '/min', q(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
      '-WindowStyle', 'Hidden', '-File', q(script), '-Plan', q(plan), '-WaitPid', String(process.pid),
      '-Relaunch', q(process.execPath)].join(' ');
    const child = spawn(cmd, ['/d', '/s', '/c', `"${line}"`], {
      detached: true, stdio: 'ignore', windowsHide: true, windowsVerbatimArguments: true,
    });
    child.on('error', (err) => updateLog(`launcher error: ${err && err.message}`));
    child.unref();
    updateLog(`launcher started: pid ${child.pid}: ${line}`);
  } catch (err) {
    updateLog(`powershell did not start: ${err && err.message}`);
    bridge.start();
    return { ok: false, message: String(err && err.message ? err.message : err) };
  }
  for (const w of BrowserWindow.getAllWindows()) w.destroy();
  // A moment for the script to start before this process (its parent) goes.
  setTimeout(() => { updateLog('exiting'); app.exit(0); }, 700);
  return { ok: true };
}

ipcMain.handle('app:applyUpdate', (_evt, planPath) => applyUpdatePlan(planPath));

// Tests (CI): the packaged app applies a prepared plan by itself, the same way
// as the button, once (not again after it comes back: result.json is there).
const TEST_APPLY_PLAN = process.env.HAMENAGEN_TEST_APPLY_PLAN || '';
function maybeTestApply() {
  if (!TEST_APPLY_PLAN) return;
  const result = path.join(path.dirname(TEST_APPLY_PLAN), 'result.json');
  if (fs.existsSync(TEST_APPLY_PLAN) && !fs.existsSync(result)) {
    updateLog('test: applying the prepared plan in 3 s');
    setTimeout(() => {
      applyUpdatePlan(TEST_APPLY_PLAN).then((r) => updateLog(`test: ${JSON.stringify(r)}`))
        .catch((err) => updateLog(`test: failed ${err && err.stack}`));
    }, 3000);
  }
}

// --- searching from inside the app ---------------------------------------------------------
// Where the network blocks programs from searching YouTube (NetFree), the
// listener searches Google, with "יוטיוב" added, inside the player's own
// window: the page takes the place of the view's content, under a bar the
// renderer draws (back, the query, forward and back in the search). It is a
// plain, sandboxed page in its own session (no downloads, no permissions); it
// may only browse Google, and a click on a YouTube result is caught and handed
// to the player instead of opening. Esc goes back to the player.
let searchView = null;
let searchShown = false;
// Tests point the search at a page of their own (tests/ui); never set in use.
const SEARCH_BASE = process.env.HAMENAGEN_TEST_SEARCH_BASE || '';

function youtubeLinkIn(url) {
  try {
    const u = new URL(url);
    // Google's redirect: /url?q=<the result>
    if (/(^|\.)google\.[a-z.]+$/.test(u.hostname) && u.pathname === '/url') {
      const target = u.searchParams.get('q') || u.searchParams.get('url');
      return target ? youtubeLinkIn(target) : null;
    }
    const host = u.hostname.replace(/^(www|m|music)\./, '');
    if (host === 'youtu.be' || host === 'youtube.com') {
      if (host === 'youtube.com' && /^\/(results|feed|signin|account)/.test(u.pathname)) return null;
      // One song, not the "mix" YouTube starts from a result (list=RD…, start_radio=1).
      if (host === 'youtube.com' && u.pathname === '/watch' && /^[\w-]{11}$/.test(u.searchParams.get('v') || '')) {
        return `https://www.youtube.com/watch?v=${u.searchParams.get('v')}`;
      }
      return u.toString();
    }
  } catch { /* not a URL */ }
  return null;
}

function isGoogle(url) {
  if (SEARCH_BASE && String(url).startsWith(SEARCH_BASE)) return true;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && /(^|\.)google\.[a-z.]+$/.test(u.hostname);
  } catch {
    return false;
  }
}

/** YouTube's own results page: the same page the browser shows (1.5.7). */
function youtubeSearchUrl(query) {
  const q = String(query || '').trim();
  if (SEARCH_BASE) return `${SEARCH_BASE}?q=${encodeURIComponent(q)}`;
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`;
}
/** A page the search view may show besides Google's: YouTube's results (and its consent screen). */
function isYoutubeResults(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:') return false;
    if (u.hostname === 'consent.youtube.com') return true;
    return /(^|\.)youtube\.com$/.test(u.hostname) && /^\/(results|feed|signin|account|$)/.test(u.pathname);
  } catch {
    return false;
  }
}

function googleSearchUrl(query) {
  // 1.5.6: as in the download-from-YouTube program, where this search shows the YouTube videos with their
  // pictures: the English word "youtube" after the words, and no language parameter (Google answers in
  // the Hebrew of the request's Accept-Language).
  const q = `${String(query || '').trim()} youtube`.trim();
  if (SEARCH_BASE) return `${SEARCH_BASE}?q=${encodeURIComponent(q)}`;
  return `https://www.google.com/search?q=${encodeURIComponent(q)}`;
}

function toWindow(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, payload);
}

function searchState() {
  if (!searchView || searchView.webContents.isDestroyed()) return;
  const wc = searchView.webContents;
  toWindow('search:state', {
    canGoBack: wc.navigationHistory.canGoBack(),
    canGoForward: wc.navigationHistory.canGoForward(),
    loading: wc.isLoading(),
  });
}

function hideSearch(reason) {
  const was = searchShown || nativeShown;
  if (searchShown && mainWindow && !mainWindow.isDestroyed()) mainWindow.contentView.removeChildView(searchView);
  if (nativeShown && nativeSearch) nativeSearch.hide();
  searchShown = false;
  nativeShown = false;
  if (was && reason) toWindow('search:closed', { reason });
}

// --- 1.5.9: the search in Edge's engine (WebView2), as in the download-from-YouTube program ----------------
// Google gives Electron's own Chromium a plainer page (no pictures, no video cards); in WebView2 — Edge, the
// engine of the download program, where the search looks right — it gives the full one. On Windows the
// search opens there (electron/searchwin.js, backend/hamenagen/searchwin.py): a window owned by the player's,
// laid over the place of the search. If it cannot start (no WebView2 runtime), the player's own view is used.
const NATIVE_SEARCH = process.platform === 'win32' && process.env.HAMENAGEN_SEARCH_VIEW !== 'electron';
let nativeSearch = null;
let nativeShown = false;
let lastSearchRect = null;
let followingWindow = false;

function searchLog(line) {
  try {
    fs.mkdirSync(path.join(DATA_DIR, 'logs'), { recursive: true });
    fs.appendFileSync(path.join(DATA_DIR, 'logs', 'search.log'), `${new Date().toISOString()} ${String(line).trim()}\n`);
  } catch { /* no log */ }
}

function onNativeSearchEvent(msg) {
  if (msg.event === 'link' && msg.url) {
    hideSearch();
    toWindow('search:link', { url: msg.url });
  } else if (msg.event === 'escape') {
    hideSearch('escape');
  } else if (msg.event === 'blocked') {
    toWindow('search:blocked', { site: msg.site || 'youtube' });
  } else if (msg.event === 'state') {
    toWindow('search:state', { canGoBack: true, canGoForward: true, loading: false });
  } else if (msg.event === 'exit') {
    nativeShown = false;
  }
}

function nativeSearchFor() {
  if (!NATIVE_SEARCH) return null;
  if (!nativeSearch) {
    nativeSearch = new NativeSearch({
      pythonPath: bridge.pythonPath,
      backendDir: bridge.backendDir,
      profileDir: path.join(DATA_DIR, 'search-profile'),
      onEvent: onNativeSearchEvent,
      log: searchLog,
    });
  }
  return nativeSearch.failed ? null : nativeSearch;
}

function ownerHwnd() {
  const b = mainWindow.getNativeWindowHandle();
  return b.length >= 8 ? b.readBigUInt64LE(0).toString() : String(b.readUInt32LE(0));
}

/** The page's rectangle (CSS pixels) as physical pixels on the screen, where the WebView2 window stands. */
function screenRect(rect) {
  const z = mainWindow.webContents.getZoomFactor() || 1;
  const cb = mainWindow.getContentBounds();
  const dip = {
    x: Math.round(cb.x + rect.x * z), y: Math.round(cb.y + rect.y * z),
    width: Math.max(1, Math.round(rect.width * z)), height: Math.max(1, Math.round(rect.height * z)),
  };
  const r = process.platform === 'win32' ? screen.dipToScreenRect(mainWindow, dip) : dip;
  return [r.x, r.y, r.width, r.height];
}

function followWindow() {
  if (followingWindow || !mainWindow) return;
  followingWindow = true;
  const again = () => {
    if (nativeShown && nativeSearch && lastSearchRect && mainWindow && !mainWindow.isDestroyed()) {
      nativeSearch.place(screenRect(lastSearchRect));
    }
  };
  for (const evt of ['move', 'resize', 'maximize', 'unmaximize', 'restore', 'enter-full-screen', 'leave-full-screen']) {
    mainWindow.on(evt, again);
  }
}

/** The user agent without the program's own tokens ("Electron/44…", "hamenagen/1.5.6"). */
function browserUserAgent(ua) {
  const keep = /^(Mozilla|AppleWebKit|Chrome|Safari)\//;
  return String(ua || '').split(' ').filter((t) => !(/^[^/()]+\/\d/.test(t) && !keep.test(t))).join(' ');
}

/**
 * 1.5.8: what a browser says about itself. Chrome and Edge (so the WebView2 window of the download-from-YouTube
 * program) send Client Hints — "Sec-CH-UA", "-Mobile", "-Platform" — with every request; Electron sends none,
 * and Google gives a window that says nothing a plainer results page (no pictures, no video cards). The window
 * is Chromium all the same, so it says it, in the headers and in ``navigator.userAgentData``.
 */
function browserHints() {
  const full = process.versions.chrome || '120.0.0.0';
  const major = full.split('.')[0];
  const platform = process.platform === 'win32' ? 'Windows' : process.platform === 'darwin' ? 'macOS' : 'Linux';
  return {
    major, full, platform,
    header: `"Chromium";v="${major}", "Google Chrome";v="${major}", "Not-A.Brand";v="24"`,
  };
}

/** Client Hints headers on the search view's requests, and the same brands for the page's scripts. */
async function giveBrowserIdentity(wc, ses, userAgent) {
  const hints = browserHints();
  ses.webRequest.onBeforeSendHeaders((details, done) => {
    const headers = { ...details.requestHeaders };
    if (!headers['Sec-CH-UA']) {
      headers['Sec-CH-UA'] = hints.header;
      headers['Sec-CH-UA-Mobile'] = '?0';
      headers['Sec-CH-UA-Platform'] = `"${hints.platform}"`;
    }
    done({ requestHeaders: headers });
  });
  try {
    if (!wc.debugger.isAttached()) {
      await wc.loadURL('about:blank');           // the debugger needs a page to attach to
      wc.debugger.attach('1.3');
    }
    await wc.debugger.sendCommand('Emulation.setUserAgentOverride', {
      userAgent,
      acceptLanguage: 'he-IL,he,en-US,en',
      userAgentMetadata: {
        brands: [{ brand: 'Chromium', version: hints.major }, { brand: 'Google Chrome', version: hints.major },
          { brand: 'Not-A.Brand', version: '24' }],
        fullVersionList: [{ brand: 'Chromium', version: hints.full }, { brand: 'Google Chrome', version: hints.full },
          { brand: 'Not-A.Brand', version: '24.0.0.0' }],
        platform: hints.platform, platformVersion: process.platform === 'win32' ? '10.0.0' : '', architecture: 'x86',
        bitness: '64', model: '', mobile: false, wow64: false,
      },
    });
  } catch { /* the headers still go; only the page's own view of its brands stays as it was */ }
}

function ensureSearchView() {
  if (searchView && !searchView.webContents.isDestroyed()) return searchView;
  const ses = session.fromPartition('persist:websearch');
  // 1.5.6: Google answers a program (an "Electron/…" and the app's name in the user agent) with a plainer
  // page: video thumbnails that stay blank, no big video on top. The window is Chromium all the same, so
  // it says what a browser says, in Hebrew.
  const cleanAgent = browserUserAgent(ses.getUserAgent());
  ses.setUserAgent(cleanAgent, 'he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7');
  ses.setPermissionRequestHandler((_wc, _perm, done) => done(false));
  ses.on('will-download', (e) => e.preventDefault());
  searchView = new WebContentsView({
    webPreferences: {
      session: ses,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
      backgroundThrottling: false,
    },
  });
  searchView.setBackgroundColor('#ffffff');
  const wc = searchView.webContents;
  wc.setAudioMuted(true);            // a search page never plays: the listener hears the player
  const catchLink = (event, target) => {
    const link = youtubeLinkIn(target);
    if (link) {
      event.preventDefault();
      hideSearch();
      toWindow('search:link', { url: link });
      return;
    }
    if (!isGoogle(target) && !isYoutubeResults(target)) event.preventDefault();   // only Google and YouTube's results
  };
  // YouTube moves between its pages without loading them (history.pushState): a click on a video shows
  // up only here. The link goes to the player, and the page is emptied, so that nothing plays in it.
  wc.on('did-navigate-in-page', (_event, target) => {
    const link = youtubeLinkIn(target);
    if (!link) return;
    hideSearch();
    toWindow('search:link', { url: link });
    setTimeout(() => { if (!wc.isDestroyed()) wc.loadURL('about:blank'); }, 50);   // the watch page must not play on
  });
  wc.on('will-navigate', catchLink);
  wc.on('will-redirect', catchLink);
  wc.setWindowOpenHandler(({ url: target }) => {
    catchLink({ preventDefault() {} }, target);
    if (!youtubeLinkIn(target) && isGoogle(target)) wc.loadURL(target);   // a "new tab" stays in place
    return { action: 'deny' };
  });
  // 1.5.8: behind NetFree, YouTube's own page is a "oops" page of the filter. Say so, and the player goes to Google.
  wc.on('did-finish-load', async () => {
    try {
      const host = new URL(wc.getURL()).hostname;
      if (!/(^|\.)youtube\.com$/.test(host)) return;
      const blocked = await wc.executeJavaScript(
        "/netfree/i.test(document.title + ' ' + (document.documentElement ? document.documentElement.innerHTML.slice(0, 20000) : ''))");
      if (blocked) toWindow('search:blocked', { site: 'youtube' });
    } catch { /* the page went away */ }
  });
  wc.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && input.key === 'Escape') {
      event.preventDefault();
      hideSearch('escape');
    }
  });
  for (const evt of ['did-navigate', 'did-navigate-in-page', 'did-start-loading', 'did-stop-loading']) wc.on(evt, searchState);
  searchView.identity = giveBrowserIdentity(wc, ses, cleanAgent);   // done before the first page is asked for
  return searchView;
}

function placeSearch(rect) {
  if (!searchView || !mainWindow || !rect) return;
  const z = mainWindow.webContents.getZoomFactor() || 1;   // the page's CSS pixels to the window's
  searchView.setBounds({
    x: Math.round(rect.x * z), y: Math.round(rect.y * z),
    width: Math.max(0, Math.round(rect.width * z)), height: Math.max(0, Math.round(rect.height * z)),
  });
}

// --- 1.7.3: a search engine's links, read by the browser engine -------------------------------------------
// Behind NetFree a search from the core (a program, not a browser) gets nothing useful from Google or Bing,
// while the same search in a browser works. So the singer's channel and songs are looked for in a hidden
// window of the player's own browser engine, with the search window's session (its cookies and consent),
// as a browser: the links of the results page are read and handed to the core. Nothing is shown or played.
let linksWindow = null;
function ensureLinksWindow() {
  if (linksWindow && !linksWindow.isDestroyed()) return linksWindow;
  const ses = session.fromPartition('persist:websearch');
  ses.setUserAgent(browserUserAgent(ses.getUserAgent()), 'he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7');
  linksWindow = new BrowserWindow({
    show: false, width: 1200, height: 900,
    webPreferences: { session: ses, sandbox: true, contextIsolation: true, nodeIntegration: false, spellcheck: false,
      backgroundThrottling: false },
  });
  linksWindow.webContents.setAudioMuted(true);
  linksWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  linksWindow.webContents.session.on('will-download', (e) => e.preventDefault());
  return linksWindow;
}

const LINK_ENGINES = SEARCH_BASE ? [(q) => `${SEARCH_BASE}?q=${encodeURIComponent(q)}`] : [
  (q) => `https://www.google.com/search?q=${encodeURIComponent(q)}&num=20`,
  (q) => `https://www.bing.com/search?q=${encodeURIComponent(q)}&count=20`,
  (q) => `https://html.duckduckgo.com/html/?q=${encodeURIComponent(q)}`,
];

// 1.7.4: a results page as the browser has it — its links and its whole text. Google keeps its results in
// the page's scripts, not in plain links; Bing and DuckDuckGo send them through their own addresses. The core
// reads the YouTube links out of all of that (websearch.decode_page).
async function pageLinks(win, url) {
  const wc = win.webContents;
  await Promise.race([
    wc.loadURL(url).catch(() => {}),
    new Promise((resolve) => setTimeout(resolve, 20000)),
  ]);
  await new Promise((resolve) => setTimeout(resolve, 1500));   // results drawn by the page's scripts
  return wc.executeJavaScript(`({
    links: Array.from(document.querySelectorAll('a[href]')).slice(0, 800)
      .map((a) => [a.href, (a.innerText || a.textContent || '').trim().slice(0, 300)]),
    html: document.documentElement.outerHTML.slice(0, 4000000),
  })`, true);
}

// A YouTube video or channel somewhere in the page, plain, escaped (=, %2F) or in Bing's base64.
const YOUTUBE_IN_PAGE = /youtube\.com(?:\/|\\\/|%2F)(?:watch|channel|@|shorts)|youtu\.be(?:\/|%2F)|aHR0cHM6Ly93d3cueW91dHViZS5jb2/i;

ipcMain.handle('search:links', async (_evt, query) => {
  if (typeof query !== 'string' || !query.trim() || query.length > 200) return { ok: false, links: [], page: '' };
  const win = ensureLinksWindow();
  for (const engine of LINK_ENGINES) {
    const host = new URL(engine('x')).hostname;
    try {
      const got = (await pageLinks(win, engine(query.trim()))) || {};
      const links = Array.isArray(got.links) ? got.links : [];
      const html = typeof got.html === 'string' ? got.html : '';
      const found = YOUTUBE_IN_PAGE.test(html) || links.some(([href]) => YOUTUBE_IN_PAGE.test(String(href)));
      searchLog(`links for "${query}" from ${host}: ${links.length} links, page ${html.length} chars, YouTube ${found ? 'found' : 'not found'} (${win.webContents.getURL().slice(0, 80)})`);
      if (found) return { ok: true, links: links.slice(0, 800), page: html, engine: host };
    } catch (err) {
      searchLog(`links for "${query}" from ${host}: ${err.message}`);
    }
  }
  return { ok: false, links: [], page: '' };
});

ipcMain.handle('search:open', async (_evt, query, rect, source) => {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false };
  const url = query != null ? (source === 'google' ? googleSearchUrl(query) : youtubeSearchUrl(query)) : null;
  const native = nativeSearchFor();
  if (native && rect) {
    try {
      await native.start(ownerHwnd());
      followWindow();
      lastSearchRect = rect;
      native.open(url, screenRect(rect));
      nativeShown = true;
      return { ok: true, engine: 'webview2' };
    } catch (err) {
      searchLog(`WebView2 window unavailable, the player's own view instead: ${err.message}`);
    }
  }
  const view = ensureSearchView();
  await view.identity;
  if (!searchShown) {
    mainWindow.contentView.addChildView(view);
    searchShown = true;
  }
  placeSearch(rect);
  if (query != null) view.webContents.loadURL(source === 'google' ? googleSearchUrl(query) : youtubeSearchUrl(query));
  view.webContents.focus();
  return { ok: true };
});
ipcMain.handle('search:place', (_evt, rect) => {
  if (nativeShown && nativeSearch && rect) {
    lastSearchRect = rect;
    nativeSearch.place(screenRect(rect));
    return;
  }
  if (searchShown) placeSearch(rect);
});
ipcMain.handle('search:hide', () => hideSearch());
ipcMain.handle('search:nav', (_evt, action) => {
  if (nativeShown && nativeSearch) {
    nativeSearch.nav(action);
    return;
  }
  if (!searchView || searchView.webContents.isDestroyed()) return;
  const history = searchView.webContents.navigationHistory;
  if (action === 'back' && history.canGoBack()) history.goBack();
  else if (action === 'forward' && history.canGoForward()) history.goForward();
  else if (action === 'reload') searchView.webContents.reload();
});

// A YouTube link the listener copied (in the browser, when the network blocks
// searching from the app). Only such a link is handed to the window.
ipcMain.handle('app:clipboardLink', () => {
  const text = (clipboard.readText() || '').trim();
  const m = text.match(/https?:\/\/(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\/[^\s<>"']+/i)
    || text.match(/https?:\/\/open\.spotify\.com\/[^\s<>"']+/i);   // 1.7: Spotify links too
  return m ? m[0] : '';
});

ipcMain.handle('app:showItemInFolder', (_evt, filePath) => {
  if (typeof filePath === 'string' && fs.existsSync(filePath)) {
    shell.showItemInFolder(filePath);
    return { ok: true };
  }
  return { ok: false };
});

ipcMain.handle('app:openFolder', async (_evt, folder) => {
  if (typeof folder !== 'string' || !folder) return { ok: false };
  fs.mkdirSync(folder, { recursive: true });
  const err = await shell.openPath(folder);
  return { ok: !err, error: err || undefined };
});

ipcMain.handle('app:chooseFolder', async (_evt, title) => {
  const res = await dialog.showOpenDialog(mainWindow, {
    title: typeof title === 'string' ? title : 'בחירת תיקייה',
    properties: ['openDirectory'],
  });
  return res.canceled || !res.filePaths.length ? null : res.filePaths[0];
});

ipcMain.handle('app:chooseFile', async (_evt, title, kind) => {
  const filters = kind === 'singers'
    ? [{ name: 'רשימת זמרים', extensions: ['csv', 'tsv', 'txt', 'json'] }, { name: 'כל הקבצים', extensions: ['*'] }]
    : kind === 'playlist'
      ? [{ name: 'רשימת השמעה', extensions: ['m3u', 'm3u8', 'pls', 'csv', 'zip'] }, { name: 'כל הקבצים', extensions: ['*'] }]
      : [{ name: 'כל הקבצים', extensions: ['*'] }];
  const res = await dialog.showOpenDialog(mainWindow, {
    title: typeof title === 'string' ? title : 'בחירת קובץ',
    properties: ['openFile'],
    filters,
  });
  return res.canceled || !res.filePaths.length ? null : res.filePaths[0];
});

// --- 1.5.1: is the player in front? (hands-free listening) -------------------------------
// In front: the window has the focus, not minimized. It stays "in front" when it
// had the focus and the computer then went idle, locked or blanked the screen
// (the screen saver takes the focus without the listener using anything else),
// until someone works in another program. Hidden, minimized or behind another
// program that is in use: not in front, and the microphone listens only on a click.
let frontNow = false;
let frontTimer = null;

function computeFront() {
  if (!mainWindow || mainWindow.isDestroyed() || !mainWindow.isVisible() || mainWindow.isMinimized()) return false;
  if (mainWindow.isFocused()) return true;
  let idle = 'active';
  try { idle = powerMonitor.getSystemIdleState(20); } catch { /* unknown: treat as in use */ }
  return frontNow && (idle === 'idle' || idle === 'locked');
}

function updateFront() {
  const next = computeFront();
  if (next === frontNow) return;
  frontNow = next;
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('app:front', { front: next });
}

function watchFront() {
  for (const evt of ['focus', 'blur', 'minimize', 'restore', 'show', 'hide']) {
    mainWindow.on(evt, () => setTimeout(updateFront, evt === 'blur' ? 300 : 0));
  }
  clearInterval(frontTimer);
  frontTimer = setInterval(updateFront, 2000);
  for (const evt of ['lock-screen', 'unlock-screen', 'suspend', 'resume']) {
    powerMonitor.on(evt, () => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('app:power', { event: evt });
      updateFront();
    });
  }
}

ipcMain.handle('app:front', () => frontNow);

ipcMain.on('player:state', (_evt, state) => {
  playerState = { playing: !!(state && state.playing), hasTrack: !!(state && state.hasTrack) };
  updateThumbar();
});

// --- Windows: desktop shortcut for the ZIP editions (spec §4) ----------------------------
function ensureDesktopShortcut() {
  if (process.platform !== 'win32' || !app.isPackaged || INSTALLED) return;
  try {
    const shortcut = path.join(app.getPath('desktop'), 'המנגן.lnk');
    let current = null;
    try { current = shell.readShortcutLink(shortcut); } catch { /* none yet */ }
    const same = (a, b) => path.normalize(a || '').toLowerCase() === path.normalize(b || '').toLowerCase();
    if (!current || !same(current.target, process.execPath)) {
      // Create it, or point it here again after the folder was moved.
      shell.writeShortcutLink(shortcut, current ? 'replace' : 'create', {
        target: process.execPath,
        cwd: path.dirname(process.execPath),
        icon: process.execPath,
        iconIndex: 0,
        description: 'המנגן — נגן מוזיקה קהילתי חכם',
        appUserModelId: APP_ID,
      });
    }
  } catch (err) {
    process.stderr.write(`[shortcut] ${err}\n`);
  }
}

app.whenReady().then(() => {
  if (process.platform === 'win32') app.setAppUserModelId(APP_ID);
  protocol.handle('cover', (request) => {
    let key = '';
    try { key = new URL(request.url).hostname; } catch { /* bad url */ }
    const file = COVER_KEY.test(key) ? coverFile(key) : '';
    if (!file) return new Response(null, { status: 404 });
    return net.fetch(pathToFileURL(file).toString());
  });
  bridge.start();
  ensureDesktopShortcut();
  createWindow();
  maybeTestApply();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  bridge.stop();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (nativeSearch) nativeSearch.stop();
  bridge.stop();
});
