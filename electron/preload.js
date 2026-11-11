'use strict';

/**
 * Preload script — exposes a minimal, safe API to the renderer.
 *
 * With context isolation and the sandbox on, the renderer never touches Node
 * or the core directly; it can only call the named functions below. Each core
 * call is checked against an allowlist again in the main process.
 */

const { contextBridge, ipcRenderer } = require('electron');
const { pathToFileURL } = require('url');

const core = (method, params) => ipcRenderer.invoke('backend', method, params || {});

function listen(channel, handler) {
  const listener = (_evt, msg) => handler(msg);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('hamenagen', {
  // A correct file:// URL for a local path (Windows drive letters,
  // backslashes, Hebrew and spaced names) for the <audio> element.
  fileUrl: (p) => {
    try { return pathToFileURL(p).href; } catch { return ''; }
  },

  // The Python core. Every call resolves to { ok, result } or { ok:false, error }.
  appInfo: () => core('app_info'),
  today: () => core('today'),
  ask: (text) => core('handle_request', { text }),
  playlist: (kind, opts) => core('playlist', { kind, ...(opts || {}) }),
  setFavorite: (id, on) => core('set_favorite', { id, on }),
  recordPlay: (id) => core('record_play', { id }),
  lyrics: (id) => core('track_lyrics', { id }),
  overview: () => core('library_overview'),
  listTracks: (query) => core('list_tracks', query),
  topics: () => core('topics'),
  rescan: (roots) => core('rescan_async', roots ? { roots } : {}),
  classifierStatus: () => core('classifier_status'),
  installModel: () => core('install_model_async'),
  reclassify: () => core('reclassify_async'),
  getSettings: () => core('get_settings'),
  updateSettings: (settings) => core('update_settings', { settings }),
  radioList: (refresh) => core('radio_list', { refresh }),
  checkUpdates: (manual) => core('check_updates', { manual: !!manual }),
  applyUpdate: (component, url, version) => core('apply_update', { component, url, version }),
  offlinePackStatus: () => core('offline_pack_status'),
  installOfflinePack: (path) => core('install_offline_pack', { path }),
  onlineAvailable: () => core('online_available'),
  onlineSearch: (query, limit) => core('online_search', { query, limit }),
  onlineDownload: (result, downloadId) => core('online_download', { result, download_id: downloadId }),

  // The operating system.
  shellInfo: () => ipcRenderer.invoke('app:info'),
  setTheme: (theme) => ipcRenderer.invoke('app:setTheme', theme),
  openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
  showInFolder: (filePath) => ipcRenderer.invoke('app:showItemInFolder', filePath),
  openFolder: (folder) => ipcRenderer.invoke('app:openFolder', folder),
  chooseFolder: (title) => ipcRenderer.invoke('app:chooseFolder', title),
  playerState: (state) => ipcRenderer.send('player:state', state),

  // Pushed notifications: core events, theme changes, taskbar buttons.
  onBackendEvent: (handler) => listen('backend:event', handler),
  onThemeChange: (handler) => listen('app:theme', handler),
  onPlayerCommand: (handler) => listen('player:command', handler),
});
