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
  app, BrowserWindow, Menu, WebContentsView, clipboard, dialog, ipcMain, nativeImage, nativeTheme, net, protocol, screen,
  session, shell,
} = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { BackendBridge } = require('./backend_bridge');

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
  mainWindow.on('closed', () => { mainWindow = null; });

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
  'online_available', 'online_search', 'online_download', 'online_link',
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

function googleSearchUrl(query) {
  const q = `${String(query || '').trim()} יוטיוב`.trim();
  if (SEARCH_BASE) return `${SEARCH_BASE}?q=${encodeURIComponent(q)}`;
  return `https://www.google.com/search?hl=iw&q=${encodeURIComponent(q)}`;
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
  if (searchShown && mainWindow && !mainWindow.isDestroyed()) mainWindow.contentView.removeChildView(searchView);
  const was = searchShown;
  searchShown = false;
  if (was && reason) toWindow('search:closed', { reason });
}

function ensureSearchView() {
  if (searchView && !searchView.webContents.isDestroyed()) return searchView;
  const ses = session.fromPartition('persist:websearch');
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
    },
  });
  searchView.setBackgroundColor('#ffffff');
  const wc = searchView.webContents;
  const catchLink = (event, target) => {
    const link = youtubeLinkIn(target);
    if (link) {
      event.preventDefault();
      hideSearch();
      toWindow('search:link', { url: link });
      return;
    }
    if (!isGoogle(target)) event.preventDefault();   // only Google, inside the player
  };
  wc.on('will-navigate', catchLink);
  wc.on('will-redirect', catchLink);
  wc.setWindowOpenHandler(({ url: target }) => {
    catchLink({ preventDefault() {} }, target);
    if (!youtubeLinkIn(target) && isGoogle(target)) wc.loadURL(target);   // a "new tab" stays in place
    return { action: 'deny' };
  });
  wc.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && input.key === 'Escape') {
      event.preventDefault();
      hideSearch('escape');
    }
  });
  for (const evt of ['did-navigate', 'did-navigate-in-page', 'did-start-loading', 'did-stop-loading']) wc.on(evt, searchState);
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

ipcMain.handle('search:open', (_evt, query, rect) => {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false };
  const view = ensureSearchView();
  if (!searchShown) {
    mainWindow.contentView.addChildView(view);
    searchShown = true;
  }
  placeSearch(rect);
  if (query != null) view.webContents.loadURL(googleSearchUrl(query));
  view.webContents.focus();
  return { ok: true };
});
ipcMain.handle('search:place', (_evt, rect) => { if (searchShown) placeSearch(rect); });
ipcMain.handle('search:hide', () => hideSearch());
ipcMain.handle('search:nav', (_evt, action) => {
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
  const m = text.match(/https?:\/\/(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\/[^\s<>"']+/i);
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
    : [{ name: 'כל הקבצים', extensions: ['*'] }];
  const res = await dialog.showOpenDialog(mainWindow, {
    title: typeof title === 'string' ? title : 'בחירת קובץ',
    properties: ['openFile'],
    filters,
  });
  return res.canceled || !res.filePaths.length ? null : res.filePaths[0];
});

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

app.on('before-quit', () => bridge.stop());
