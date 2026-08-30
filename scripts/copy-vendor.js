'use strict';

/**
 * Copy third-party browser libraries from node_modules into the renderer's
 * vendor folder, so index.html can load them locally (offline, CSP-friendly).
 *
 * Runs on `npm install` (postinstall). If a source is missing we warn and
 * continue — the app degrades gracefully (e.g. HLS radio needs hls.js; without
 * it, non-HLS streams still play via the native <audio> element).
 */

const fs = require('fs');
const path = require('path');

const vendorDir = path.join(__dirname, '..', 'electron', 'renderer', 'vendor');
fs.mkdirSync(vendorDir, { recursive: true });

const items = [
  { from: path.join('hls.js', 'dist', 'hls.min.js'), to: 'hls.min.js' },
];

for (const item of items) {
  const src = path.join(__dirname, '..', 'node_modules', item.from);
  const dest = path.join(vendorDir, item.to);
  try {
    fs.copyFileSync(src, dest);
    console.log(`[vendor] copied ${item.to}`);
  } catch (err) {
    console.warn(`[vendor] skipped ${item.to}: ${err.message}`);
  }
}
