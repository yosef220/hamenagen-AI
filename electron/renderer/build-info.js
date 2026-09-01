// Build identity for the app-update check. CI overwrites this file at build
// time with the real commit SHA; the default below marks a local/dev build.
window.__BUILD__ = {
  version: '0.1.0',
  build: 'dev',
  zip_url:
    'https://github.com/yosef220/hamenagen-AI/releases/download/portable-latest/hamenagen-0.1.0.zip',
};
