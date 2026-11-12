'use strict';

/**
 * The app as update parts — an electron-builder afterPack hook.
 *
 * Right after the app is laid out in win-unpacked (and before the ZIP or the
 * installer is made from it) this writes resources/parts.json: every part of
 * the app with a fingerprint of its content. An installed copy compares its
 * own parts.json with the one a new release publishes, and downloads only
 * the parts whose fingerprint changed (see backend/hamenagen/smart_update.py
 * and scripts/make_parts.py).
 *
 * Parts: "runtime" (Electron, at the program's root), "app" (app.asar and the
 * other files beside it in resources), and each folder in resources
 * (backend, python, ffmpeg, audio-models, models).
 *
 * The fingerprint of a part is the SHA-256 of its file list — one line per
 * file, "path<TAB>size<TAB>sha256", sorted by UTF-8 bytes — the same as
 * content_hash() in smart_update.py. Two parts stand on a description rather
 * than their bytes, because their bytes change on every build while what
 * they do does not: the runtime (the program's version is written into
 * Hamenagen.exe) by the Electron version, its fuses and the icon; ffmpeg by
 * its version line.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const MAIN_EXE = 'Hamenagen.exe';

function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex');
}

function fileHash(full) {
  const hash = crypto.createHash('sha256');
  const fd = fs.openSync(full, 'r');
  const buf = Buffer.alloc(1 << 20);
  try {
    let n;
    while ((n = fs.readSync(fd, buf, 0, buf.length, null)) > 0) hash.update(buf.subarray(0, n));
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest('hex');
}

// Python's compiled caches are not part of the program: Python writes them
// next to the code on its first run, so they are never hashed or packed
// (the same rule as smart_update.py and make_parts.py).
const CACHE_DIR = '__pycache__';
const isCacheFile = (name) => name.endsWith('.pyc');

function walk(dir, out) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name !== CACHE_DIR) walk(full, out);
    } else if (ent.isFile() && !isCacheFile(ent.name)) out.push(full);
  }
  return out;
}

/** Delete Python's caches under `dir` (left by build steps that ran Python). */
function removeCaches(dir) {
  let removed = 0;
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name === CACHE_DIR) {
        fs.rmSync(full, { recursive: true, force: true });
        removed += 1;
      } else removed += removeCaches(full);
    } else if (ent.isFile() && isCacheFile(ent.name)) {
      fs.rmSync(full, { force: true });
      removed += 1;
    }
  }
  return removed;
}

const byUtf8 = (a, b) => Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'));

/** { hash, files, size } of the files under `entries` (relative to `base`). */
function contentHash(base, entries, skip = new Set()) {
  const files = [];
  for (const entry of entries) {
    const full = path.join(base, entry);
    if (fs.statSync(full).isDirectory()) walk(full, files);
    else files.push(full);
  }
  const rels = files.map((f) => path.relative(base, f).split(path.sep).join('/')).filter((r) => !skip.has(r)).sort(byUtf8);
  let size = 0;
  const lines = rels.map((r) => {
    const full = path.join(base, ...r.split('/'));
    const n = fs.statSync(full).size;
    size += n;
    return `${r}\t${n}\t${fileHash(full)}\n`;
  });
  return { hash: sha256(lines.join('')), files: rels.length, size };
}

function describeParts({ appOutDir, version, edition, electronVersion, fuses, iconFile }) {
  const resources = path.join(appOutDir, 'resources');
  const parts = {};

  // The runtime: every entry at the root except resources (and the data
  // folder a portable copy keeps there, which is never in a package).
  const rootEntries = fs.readdirSync(appOutDir).filter((n) => n !== 'resources' && n !== 'data').sort(byUtf8);
  const root = contentHash(appOutDir, rootEntries, new Set([MAIN_EXE]));
  const icon = iconFile && fs.existsSync(iconFile) ? fileHash(iconFile) : '';
  parts.runtime = {
    kind: 'root',
    entries: rootEntries,
    hash: sha256(`runtime\n${root.hash}\nelectron\t${electronVersion}\nfuses\t${JSON.stringify(fuses || {})}\nicon\t${icon}\nexe\t${MAIN_EXE}\n`),
    fingerprint: true,
    files: root.files + 1,
    size: root.size + fs.statSync(path.join(appOutDir, MAIN_EXE)).size,
  };

  const names = fs.readdirSync(resources).filter((n) => n !== 'parts.json').sort(byUtf8);
  const looseFiles = names.filter((n) => fs.statSync(path.join(resources, n)).isFile());
  if (looseFiles.length) parts.app = { kind: 'files', entries: looseFiles, ...contentHash(resources, looseFiles) };
  for (const name of names.filter((n) => fs.statSync(path.join(resources, n)).isDirectory())) {
    const part = { kind: 'dir', entries: [name], ...contentHash(resources, [name]) };
    const versionFile = path.join(resources, name, 'VERSION.txt');
    if (name === 'ffmpeg' && fs.existsSync(versionFile)) {
      const license = path.join(resources, name, 'LICENSE.txt');
      // "ffmpeg version n7.1.2-12-gabcdef-20261101 Copyright …" → the version
      // without the build date: a daily rebuild of the same version is the same part.
      const version = fs.readFileSync(versionFile, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/)[0]
        .replace(/\s+Copyright.*$/, '').replace(/-\d{8}\b/g, '').trim();
      part.hash = sha256(`ffmpeg\n${version}\n${fs.existsSync(license) ? fileHash(license) : ''}\n`);
      part.version = version;
      part.fingerprint = true;
    }
    parts[name] = part;
  }
  return { format: 1, version, edition, parts };
}

/** electron-builder afterPack: write resources/parts.json. */
async function afterPack(context) {
  if (context.electronPlatformName !== 'win32') return;
  const appOutDir = context.appOutDir;
  const config = context.packager.config || {};
  // Before the fingerprints (and before the installer is made from this
  // folder): no compiled caches in the package.
  const caches = removeCaches(path.join(appOutDir, 'resources'));
  if (caches) console.log(`[parts] removed ${caches} Python cache folders/files`);
  const electronVersion = config.electronVersion
    || require(path.join(__dirname, '..', 'node_modules', 'electron', 'package.json')).version;
  const manifest = describeParts({
    appOutDir,
    version: context.packager.appInfo.version,
    edition: process.env.HAMENAGEN_EDITION || 'portable',
    electronVersion,
    fuses: config.electronFuses,
    iconFile: path.join(__dirname, '..', 'assets', 'icon.ico'),
  });
  fs.writeFileSync(path.join(appOutDir, 'resources', 'parts.json'), JSON.stringify(manifest, null, 2));
  const sizes = Object.entries(manifest.parts).map(([n, p]) => `${n} ${(p.size / 1048576).toFixed(1)}MB`).join(', ');
  console.log(`[parts] ${manifest.edition} ${manifest.version}: ${sizes}`);
}

module.exports = afterPack;
module.exports.afterPack = afterPack;
module.exports.describeParts = describeParts;
module.exports.contentHash = contentHash;
module.exports.removeCaches = removeCaches;
