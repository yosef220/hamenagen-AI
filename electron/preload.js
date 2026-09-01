'use strict';

/**
 * Preload script — exposes a minimal, safe API to the renderer.
 *
 * With context isolation on, the renderer never touches Node or the backend
 * directly; it can only call the whitelisted methods below, each of which is
 * forwarded to the Python core in the main process.
 */

const { contextBridge, ipcRenderer } = require('electron');
const { pathToFileURL } = require('url');

const invoke = (channel, params) => ipcRenderer.invoke(channel, params);

contextBridge.exposeInMainWorld('hamenagen', {
  ping: () => invoke('backend:ping'),
  // Build a correct file:// URL for a local path (handles Windows drive
  // letters, backslashes and Hebrew/spaced filenames) for the <audio> element.
  fileUrl: (p) => {
    try { return pathToFileURL(p).href; } catch { return ''; }
  },
  ask: (text) => invoke('backend:handle_request', { text }),
  rescan: (roots) => invoke('backend:rescan', { roots }),
  rescanAsync: (roots) => invoke('backend:rescan_async', { roots }),
  openingSuggestion: () => invoke('backend:opening_suggestion'),
  radioList: (refresh) => invoke('backend:radio_list', { refresh }),
  classifierStatus: () => invoke('backend:classifier_status'),
  reclassify: () => invoke('backend:reclassify'),
  checkUpdates: () => invoke('backend:check_updates'),
  applyUpdate: (component, url, version) =>
    invoke('backend:apply_update', { component, url, version }),
  offlinePackStatus: () => invoke('backend:offline_pack_status'),
  installOfflinePack: (path) => invoke('backend:install_offline_pack', { path }),
  getSettings: () => invoke('backend:get_settings'),
  updateSettings: (settings) => invoke('backend:update_settings', { settings }),
  onlineSearch: (query, limit) => invoke('backend:online_search', { query, limit }),
  onlineDownload: (result, downloadId) =>
    invoke('backend:online_download', { result, download_id: downloadId }),
  openExternal: (url) => invoke('shell:openExternal', url),
  // Subscribe to backend events (e.g. { event: 'download_progress', ... }).
  onBackendEvent: (handler) => {
    const listener = (_evt, msg) => handler(msg);
    ipcRenderer.on('backend:event', listener);
    return () => ipcRenderer.removeListener('backend:event', listener);
  },
});
