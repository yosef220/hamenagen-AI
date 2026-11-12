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
  app, BrowserWindow, Menu, clipboard, dialog, ipcMain, nativeImage, nativeTheme, net, protocol, screen, session, shell,
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
ipcMain.handle('app:applyUpdate', async (_evt, planPath) => {
  if (process.platform !== 'win32' || !app.isPackaged) {
    return { ok: false, message: 'העדכון החכם פועל רק בתוכנה עצמה ב-Windows.' };
  }
  const work = path.join(DATA_DIR, 'update');
  const plan = typeof planPath === 'string' ? path.resolve(planPath) : '';
  if (!plan || path.dirname(plan) !== path.resolve(work) || !fs.existsSync(plan)) {
    return { ok: false, message: 'אין עדכון מוכן.' };
  }
  try {
    const script = path.join(work, 'apply.ps1');
    fs.writeFileSync(script, fs.readFileSync(path.join(__dirname, 'update-apply.ps1')));
    const powershell = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    const child = spawn(powershell, [
      '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
      '-File', script, '-Plan', plan, '-WaitPid', String(process.pid), '-Relaunch', process.execPath,
    ], { detached: true, stdio: 'ignore', windowsHide: true });
    child.unref();
  } catch (err) {
    return { ok: false, message: String(err && err.message ? err.message : err) };
  }
  setTimeout(() => app.quit(), 400);
  return { ok: true };
});

// --- searching from inside the app ---------------------------------------------------------
// Where the network blocks programs from searching YouTube (NetFree), the
// listener searches Google here, with "יוטיוב" added. The window is a plain,
// sandboxed browser in its own session (no downloads, no permissions); it
// may only browse Google, and a click on a YouTube result is caught and
// handed to the player instead of opening.
let searchWindow = null;

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
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && /(^|\.)google\.[a-z.]+$/.test(u.hostname);
  } catch {
    return false;
  }
}

function openSearchWindow(query) {
  const q = `${String(query || '').trim()} יוטיוב`.trim();
  const url = `https://www.google.com/search?hl=iw&q=${encodeURIComponent(q)}`;
  if (searchWindow && !searchWindow.isDestroyed()) {
    searchWindow.loadURL(url);
    searchWindow.focus();
    return;
  }
  const ses = session.fromPartition('persist:websearch');
  ses.setPermissionRequestHandler((_wc, _perm, done) => done(false));
  ses.on('will-download', (e) => e.preventDefault());
  searchWindow = new BrowserWindow({
    parent: mainWindow || undefined,
    width: 1000,
    height: 760,
    title: 'חיפוש בגוגל — לוחצים על תוצאה מיוטיוב',
    autoHideMenuBar: true,
    backgroundColor: '#ffffff',
    webPreferences: {
      session: ses,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
    },
  });
  searchWindow.setMenu(null);
  const wc = searchWindow.webContents;
  const catchLink = (event, target) => {
    const link = youtubeLinkIn(target);
    if (link) {
      event.preventDefault();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('search:link', { url: link });
        mainWindow.focus();
      }
      if (searchWindow && !searchWindow.isDestroyed()) searchWindow.close();
      return;
    }
    if (!isGoogle(target)) event.preventDefault();   // the window browses Google only
  };
  wc.on('will-navigate', catchLink);
  wc.on('will-redirect', catchLink);
  wc.setWindowOpenHandler(({ url: target }) => {
    catchLink({ preventDefault() {} }, target);
    return { action: 'deny' };
  });
  searchWindow.on('page-title-updated', (e) => e.preventDefault());
  searchWindow.on('closed', () => { searchWindow = null; });
  searchWindow.loadURL(url);
}

ipcMain.handle('app:searchWeb', (_evt, query) => {
  openSearchWindow(query);
  return { ok: true };
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
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  bridge.stop();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => bridge.stop());
