'use strict';

/**
 * electron-builder configuration for the three Windows editions. Pick one
 * with HAMENAGEN_EDITION (default "portable"):
 *
 *   portable — Hamenagen-<v>-Windows.zip          unzip and run; the AI model
 *                                                 downloads once on first run
 *   offline  — Hamenagen-<v>-Windows-Offline.zip  the same, with the AI model
 *                                                 inside (build/models)
 *   setup    — Hamenagen-<v>-Setup.exe            a per-user installer
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
if (!['portable', 'offline', 'setup'].includes(edition)) {
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
if (edition === 'offline') {
  config.extraResources.push({ from: 'build/models', to: 'models', filter: ['**/*'] });
  config.win.artifactName = 'Hamenagen-${version}-Windows-Offline.${ext}';
}
if (edition === 'setup') {
  config.win.target = ['nsis'];
}

module.exports = config;
