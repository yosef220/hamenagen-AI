'use strict';

/**
 * Preload script — exposes a minimal, safe API to the renderer.
 *
 * With context isolation on, the renderer never touches Node or the backend
 * directly; it can only call the whitelisted methods below, each of which is
 * forwarded to the Python core in the main process.
 */

const { contextBridge, ipcRenderer } = require('electron');

const invoke = (channel, params) => ipcRenderer.invoke(channel, params);

contextBridge.exposeInMainWorld('hamenagen', {
  ping: () => invoke('backend:ping'),
  ask: (text) => invoke('backend:handle_request', { text }),
  rescan: (roots) => invoke('backend:rescan', { roots }),
  openingSuggestion: () => invoke('backend:opening_suggestion'),
  getSettings: () => invoke('backend:get_settings'),
  updateSettings: (settings) => invoke('backend:update_settings', { settings }),
  onlineSearch: (query, limit) => invoke('backend:online_search', { query, limit }),
  onlineDownload: (result) => invoke('backend:online_download', { result }),
  openExternal: (url) => invoke('shell:openExternal', url),
});
