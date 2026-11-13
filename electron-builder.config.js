'use strict';

/**
 * electron-builder configuration for the four Windows editions. Pick one
 * with HAMENAGEN_EDITION (default "portable"). Every edition is one file:
 *
 *   portable      — Hamenagen-<v>-Portable.exe         opens itself once into a
 *                   folder you pick and runs from there; the AI model downloads
 *                   once on first run (scripts/portable.nsi, from win-unpacked)
 *   offline       — Hamenagen-<v>-Portable-Offline.exe the same, with the AI
 *                   model inside (build/models)
 *   setup         — Hamenagen-<v>-Setup.exe            a per-user installer
 *   setup-offline — Hamenagen-<v>-Setup-Offline.exe    the installer, with the
 *                   AI model inside
 *
 * After packaging, scripts/parts.js writes resources/parts.json — the parts of
 * the app and their fingerprints, for the smart update.
 *
 * Every edition carries the small vocal-detection model (build/audio-models,
 * 6 MB, from backend/scripts/prepare_audio_model.py) and ffmpeg.exe
 * (build/ffmpeg, an LGPL build, for MP3 downloads with the cover inside) when
 * they were prepared.
 *
 * The edition is written into the packaged package.json (hamenagenEdition);
 * electron/main.js reads it to decide where the data folder lives.
 */

const fs = require('fs');

const edition = process.env.HAMENAGEN_EDITION || 'portable';
if (!['portable', 'offline', 'setup', 'setup-offline'].includes(edition)) {
  throw new Error(`unknown edition: ${edition}`);
}

const backendFilter = [
  '**/*',
  '!**/__pycache__/**',
  '!**/*.pyc',
  '!tests/**',
  '!data/**',
  '!scripts/**',
  '!*.egg-info/**',
  '!.pytest_cache/**',
];

const config = {
  appId: 'org.community.hamenagen',
  productName: 'המנגן',
  executableName: 'Hamenagen',
  copyright: 'המנגן — נגן מוזיקה קהילתי',
  directories: { output: 'dist', buildResources: 'assets' },
  files: [
    'electron/**/*',
    'assets/icon.png',
    'assets/thumbar/**/*',
    'package.json',
  ],
  extraMetadata: { hamenagenEdition: edition },
  extraResources: [
    { from: 'backend', to: 'backend', filter: backendFilter },
    { from: 'build/win-python', to: 'python', filter: ['**/*'] },
  ],
  asar: true,
  // resources/parts.json, for the smart update.
  afterPack: './scripts/parts.js',
  electronFuses: {
    runAsNode: false,
    enableCookieEncryption: true,
    enableNodeOptionsEnvironmentVariable: false,
    enableNodeCliInspectArguments: false,
  },
  win: {
    target: ['zip'],
    icon: 'assets/icon.ico',
    artifactName: 'Hamenagen-${version}-Windows.${ext}',
  },
  nsis: {
    oneClick: true,
    perMachine: false,
    createDesktopShortcut: 'always',
    createStartMenuShortcut: true,
    shortcutName: 'המנגן',
    runAfterFinish: true,
    deleteAppDataOnUninstall: false,
    installerIcon: 'assets/icon.ico',
    uninstallerIcon: 'assets/icon.ico',
    uninstallDisplayName: 'המנגן',
    artifactName: 'Hamenagen-${version}-Setup.${ext}',
  },
};

if (fs.existsSync('build/audio-models')) {
  config.extraResources.push({ from: 'build/audio-models', to: 'audio-models', filter: ['**/*'] });
}
if (fs.existsSync('build/ffmpeg')) {
  config.extraResources.push({ from: 'build/ffmpeg', to: 'ffmpeg', filter: ['**/*'] });
}
const withModel = edition === 'offline' || edition === 'setup-offline';
if (withModel) {
  config.extraResources.push({ from: 'build/models', to: 'models', filter: ['**/*'] });
  // The speech model in its own part (resources/voice-models).
  if (fs.existsSync('build/voice-models')) {
    config.extraResources.push({ from: 'build/voice-models', to: 'voice-models', filter: ['**/*'] });
  }
}
if (edition === 'portable' || edition === 'offline') {
  // Only the folder; scripts/portable.nsi makes the one-file EXE from it.
  config.win.target = ['dir'];
}
if (edition === 'setup' || edition === 'setup-offline') {
  config.win.target = ['nsis'];
}
if (edition === 'setup-offline') {
  config.nsis.artifactName = 'Hamenagen-${version}-Setup-Offline.${ext}';
}

module.exports = config;
