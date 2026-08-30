'use strict';

/**
 * Electron main process (spec §6, §15).
 *
 * Owns the application window, wires renderer IPC calls to the Python core
 * through {@link BackendBridge}, and (on Windows, in a packaged build) creates
 * the desktop shortcut with the app icon on first run.
 */

const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('path');
const { BackendBridge } = require('./backend_bridge');

const bridge = new BackendBridge();
let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 820,
    minHeight: 560,
    title: 'הַמְנַגֵּן — נגן מוזיקה קהילתי חכם',
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
    backgroundColor: '#0f1020',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.removeMenu();
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.on('closed', () => (mainWindow = null));
}

// --- IPC: forward to the Python backend ------------------------------------
const FORWARD = [
  'ping',
  'handle_request',
  'rescan',
  'opening_suggestion',
  'get_settings',
  'update_settings',
  'online_search',
  'online_download',
];

for (const method of FORWARD) {
  ipcMain.handle(`backend:${method}`, async (_evt, params) => {
    try {
      return { ok: true, result: await bridge.call(method, params || {}) };
    } catch (err) {
      return { ok: false, error: String(err && err.message ? err.message : err) };
    }
  });
}

// Open the external source's results page in the system browser (spec §11).
ipcMain.handle('shell:openExternal', async (_evt, url) => {
  if (typeof url === 'string' && /^https?:\/\//.test(url)) {
    await shell.openExternal(url);
    return { ok: true };
  }
  return { ok: false, error: 'invalid url' };
});

// --- Windows: first-run desktop shortcut (spec §4) -------------------------
function ensureDesktopShortcut() {
  if (process.platform !== 'win32' || !app.isPackaged) return;
  try {
    const desktop = app.getPath('desktop');
    const shortcut = path.join(desktop, 'המנגן.lnk');
    const fs = require('fs');
    if (!fs.existsSync(shortcut)) {
      shell.writeShortcutLink(shortcut, {
        target: process.execPath,
        icon: process.execPath,
        iconIndex: 0,
        description: 'נגן מוזיקה קהילתי חכם',
      });
    }
  } catch (err) {
    process.stderr.write(`[shortcut] ${err}\n`);
  }
}

app.whenReady().then(() => {
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
