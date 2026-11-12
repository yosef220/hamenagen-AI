'use strict';

/**
 * Preload script — exposes a minimal, safe API to the renderer.
 *
 * With context isolation and the sandbox on, the renderer never touches Node
 * or the core directly; it can only call the named functions below. Each core
 * call is checked against an allowlist again in the main process.
 */

const { contextBridge, ipcRenderer } = require('electron');

/**
 * A correct file:// URL for a local path — Windows drive letters and UNC
 * shares, backslashes, Hebrew and spaced names, '#' and '%' in file names.
 * (The sandboxed preload has no Node `url.pathToFileURL`, so this is plain JS.)
 */
function toFileUrl(p) {
  if (!p) return '';
  let s = String(p).replace(/\\/g, '/');
  if (s.startsWith('//')) {
    const parts = s.slice(2).split('/');
    const host = parts.shift();
    return `file://${host}/${parts.map(encodeURIComponent).join('/')}`;
  }
  if (/^[A-Za-z]:/.test(s)) s = `/${s}`;
  const segments = s.split('/').map((seg, i) => (i === 1 && /^[A-Za-z]:$/.test(seg) ? seg : encodeURIComponent(seg)));
  return `file://${segments.join('/')}`;
}

const core = (method, params) => ipcRenderer.invoke('backend', method, params || {});

function listen(channel, handler) {
  const listener = (_evt, msg) => handler(msg);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('hamenagen', {
  // The file:// URL of a local song, for the <audio> element.
  fileUrl: (p) => toFileUrl(p),

  // The Python core. Every call resolves to { ok, result } or { ok:false, error }.
  appInfo: () => core('app_info'),
  today: () => core('today'),
  shabbatStatus: () => core('shabbat_status'),
  playlists: () => core('playlists'),
  playlistGet: (id) => core('playlist_get', { id }),
  playlistCreate: (name, trackIds) => core('playlist_create', { name, track_ids: trackIds || [] }),
  playlistRename: (id, name) => core('playlist_rename', { id, name }),
  playlistDelete: (id) => core('playlist_delete', { id }),
  playlistAdd: (id, trackIds) => core('playlist_add', { id, track_ids: trackIds }),
  playlistSetOrder: (id, trackIds) => core('playlist_set_order', { id, track_ids: trackIds }),
  trackCopies: (id) => core('track_copies', { id }),
  onlineSet: (event, topic) => core('online_set', { event, topic }),
  listenPrepare: (result) => core('listen_prepare', { result }),
  appUpdateDownload: () => core('app_update_download_async'),
  appUpdateCancel: () => core('app_update_cancel'),
  appUpdateResult: () => core('app_update_result'),
  completeDetails: () => core('complete_details_async'),
  stopCompleteDetails: () => core('stop_complete_details'),
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
  onlineLink: (url, limit) => core('online_link', { url, limit }),
  downloadBatch: (items, batchId) => core('download_batch_async', { items, batch_id: batchId }),
  stopDownloads: () => core('stop_downloads'),
  lookupDetails: (id) => core('lookup_details', { id }),
  applyDetails: (id, candidate, propagate) => core('apply_details', { id, candidate, propagate }),
  setTrackTopic: (id, topic) => core('set_track_topic', { id, topic }),
  setTrackVocal: (id, value) => core('set_track_vocal', { id, value }),
  confirmVocal: (ids, value) => core('confirm_vocal', { ids, value }),
  vocalStatus: () => core('vocal_status'),
  vocalReview: (limit) => core('vocal_review', { limit }),
  analyzeVocal: () => core('analyze_vocal_async'),
  stopVocal: () => core('stop_vocal'),

  // The operating system.
  shellInfo: () => ipcRenderer.invoke('app:info'),
  setTheme: (theme) => ipcRenderer.invoke('app:setTheme', theme),
  openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
  showInFolder: (filePath) => ipcRenderer.invoke('app:showItemInFolder', filePath),
  clipboardLink: () => ipcRenderer.invoke('app:clipboardLink'),
  // Google inside the window (electron/main.js): open it over the given
  // rectangle of the page, follow the rectangle, hide it, move in its history.
  searchOpen: (query, rect) => ipcRenderer.invoke('search:open', query, rect),
  searchPlace: (rect) => ipcRenderer.invoke('search:place', rect),
  searchHide: () => ipcRenderer.invoke('search:hide'),
  searchNav: (action) => ipcRenderer.invoke('search:nav', action),
  applyAppUpdate: (plan) => ipcRenderer.invoke('app:applyUpdate', plan),
  openFolder: (folder) => ipcRenderer.invoke('app:openFolder', folder),
  chooseFolder: (title) => ipcRenderer.invoke('app:chooseFolder', title),
  playerState: (state) => ipcRenderer.send('player:state', state),

  // Pushed notifications: core events, theme changes, taskbar buttons.
  onBackendEvent: (handler) => listen('backend:event', handler),
  onThemeChange: (handler) => listen('app:theme', handler),
  onPlayerCommand: (handler) => listen('player:command', handler),
  onSearchLink: (handler) => listen('search:link', handler),
  onSearchState: (handler) => listen('search:state', handler),
  onSearchClosed: (handler) => listen('search:closed', handler),
});
