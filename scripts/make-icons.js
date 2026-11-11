'use strict';

/**
 * Render assets/icon.svg (with its font embedded) to the PNGs the app and the
 * installer use, then build icon.ico and the taskbar button images with
 * scripts/make-icons.py. Needs Playwright's Chromium:
 *
 *   node scripts/make-icons.js
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');

const root = path.join(__dirname, '..');
const assets = path.join(root, 'assets');
const font = path.join(root, 'node_modules', '@fontsource', 'frank-ruhl-libre', 'files', 'frank-ruhl-libre-hebrew-700-normal.woff2');
const SIZES = [1024, 512, 256, 128, 64, 48, 40, 32, 24, 20, 16];

(async () => {
  const svg = fs.readFileSync(path.join(assets, 'icon.svg'), 'utf8');
  const fontData = fs.readFileSync(font).toString('base64');
  const html = `<!DOCTYPE html><html><head><style>
    @font-face { font-family: 'Frank Ruhl Libre'; font-weight: 700; src: url(data:font/woff2;base64,${fontData}) format('woff2'); }
    html, body { margin: 0; background: transparent; }
    svg { display: block; width: 100vw; height: 100vh; }
  </style></head><body>${svg}</body></html>`;
  const browser = await chromium.launch();
  const out = path.join(root, 'build', 'icons');
  fs.mkdirSync(out, { recursive: true });
  for (const size of SIZES) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    await page.setContent(html);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(out, `icon-${size}.png`), omitBackground: true });
    await page.close();
  }
  await browser.close();
  fs.copyFileSync(path.join(out, 'icon-512.png'), path.join(assets, 'icon.png'));
  execFileSync(process.env.PYTHON || 'python3', [path.join(__dirname, 'make-icons.py'), out, assets], { stdio: 'inherit' });
  console.log('icons ready');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
