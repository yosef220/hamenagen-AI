'use strict';

/*
 * The renderer's view of the Python core and the operating system.
 *
 * Every core call answers { ok, result } across the bridge; here it becomes
 * a promise of the result that rejects with a readable error. A small event
 * hub carries the core's pushed events (scan progress, downloads …) to
 * whichever view cares.
 */
(function () {
  const bridge = window.hamenagen;

  const CORE = [
    'appInfo', 'today', 'ask', 'playlist', 'setFavorite', 'recordPlay', 'lyrics', 'overview',
    'listTracks', 'topics', 'rescan', 'classifierStatus', 'installModel', 'reclassify',
    'getSettings', 'updateSettings', 'radioList', 'checkUpdates', 'applyUpdate',
    'offlinePackStatus', 'installOfflinePack', 'onlineAvailable', 'onlineSearch', 'onlineDownload',
  ];
  const SHELL = [
    'shellInfo', 'setTheme', 'openExternal', 'showInFolder', 'openFolder', 'chooseFolder', 'playerState',
  ];

  const api = {};
  for (const name of CORE) {
    api[name] = async (...args) => {
      const res = await bridge[name](...args);
      if (!res || !res.ok) throw new Error((res && res.error) || 'לא התקבלה תשובה מהליבה');
      return res.result;
    };
  }
  for (const name of SHELL) api[name] = (...args) => bridge[name](...args);
  api.fileUrl = (p) => bridge.fileUrl(p);

  // -- event hub ----------------------------------------------------------
  const handlers = new Map();
  api.on = (event, fn) => {
    if (!handlers.has(event)) handlers.set(event, new Set());
    handlers.get(event).add(fn);
    return () => handlers.get(event).delete(fn);
  };
  api.emit = (event, payload) => {
    for (const fn of handlers.get(event) || []) {
      try { fn(payload); } catch (err) { console.error(err); }
    }
  };
  bridge.onBackendEvent((msg) => api.emit(msg.event, msg));
  bridge.onThemeChange((msg) => api.emit('theme', msg));
  bridge.onPlayerCommand((cmd) => api.emit('player-command', cmd));

  H.api = api;
})();
