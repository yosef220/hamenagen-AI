'use strict';

/**
 * UI harness: launches the real app (Electron + the Python core) against a
 * demo library and takes a screenshot of every screen, in both themes.
 *
 *   xvfb-run -s "-screen 0 2800x1900x24" node tests/ui/shoot.js <music> <out> [--today=YYYY-MM-DD] [--scale=2]
 *
 * It also works as a smoke test: it fails if a screen throws, the core does
 * not answer, or a request returns nothing.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { _electron: electron } = require('playwright');

const root = path.join(__dirname, '..', '..');
const [music, out] = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const flag = (name, fallback) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.split('=')[1] : fallback;
};
const today = flag('today', '');
const scale = Number(flag('scale', '1'));
const themes = flag('themes', 'light,dark').split(',');

if (!music || !out) {
  console.error('usage: node tests/ui/shoot.js <music-folder> <out-folder> [--today=YYYY-MM-DD] [--scale=2]');
  process.exit(2);
}

const errors = [];

async function launch(dataDir, theme) {
  const settings = {
    scan_roots: [path.resolve(music)],
    theme,
    update_manifest_url: '',
  };
  fs.mkdirSync(dataDir, { recursive: true });
  const settingsFile = path.join(dataDir, 'settings.json');
  const prev = fs.existsSync(settingsFile) ? JSON.parse(fs.readFileSync(settingsFile, 'utf8')) : {};
  fs.writeFileSync(settingsFile, JSON.stringify({ ...prev, ...settings }, null, 2));
  fs.writeFileSync(path.join(dataDir, 'window.json'), JSON.stringify({ x: 0, y: 0, width: 1360, height: 860 }));

  const executablePath = require(path.join(root, 'node_modules', 'electron'));
  const app = await electron.launch({
    executablePath,
    args: ['--no-sandbox', '--disable-gpu', `--force-device-scale-factor=${scale}`, root],
    env: {
      ...process.env,
      HAMENAGEN_DATA_DIR: dataDir,
      HAMENAGEN_TODAY: today,
      HAMENAGEN_QUIET: '1',
    },
  });
  const page = await app.firstWindow();
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`console: ${msg.text()}`);
  });
  await page.waitForSelector('.luach', { timeout: 30000 });
  return { app, page };
}

async function shot(page, name) {
  await page.waitForTimeout(450);
  // Toasts are transient; keep them out of the pictures.
  await page.evaluate(() => document.querySelectorAll('.toast').forEach((t) => t.remove()));
  const file = path.join(out, `${name}.png`);
  await page.screenshot({ path: file });
  console.log('saved', file);
}

async function waitForLibrary(page) {
  await page.waitForFunction(() => /שירים|שיר אחד/.test(document.querySelector('#rail-count').textContent || ''), null, { timeout: 60000 });
}

async function run() {
  fs.mkdirSync(out, { recursive: true });
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hamenagen-ui-'));
  // What the vocal detector would have heard (the harness has no audio model).
  execFileSync(process.env.HAMENAGEN_PYTHON || 'python3', [path.join(__dirname, 'seed_vocal.py'), path.resolve(music), dataDir],
    { stdio: 'inherit' });

  for (const theme of themes) {
    const { app, page } = await launch(dataDir, theme);
    const suffix = themes.length > 1 ? `-${theme}` : '';
    try {
      await waitForLibrary(page);
      // Seed listening history and favorites through the same API the UI uses.
      await page.evaluate(async () => {
        const res = await window.hamenagen.listTracks({ sort: 'title', limit: 50 });
        const tracks = res.result.tracks;
        const pick = (t) => tracks.find((x) => x.title === t);
        for (const t of ['מנוחה ושמחה', 'ירושלים של זהב', 'בר יוחאי', 'ידיד נפש']) {
          const tr = pick(t);
          if (tr) await window.hamenagen.setFavorite(tr.id, true);
        }
        for (const t of ['לכה דודי', 'אמת', 'מעוז צור', 'ושאבתם מים', 'מנוחה ושמחה']) {
          const tr = pick(t);
          if (tr) await window.hamenagen.recordPlay(tr.id);
        }
      });
      await page.evaluate(() => H.go('home'));
      await page.waitForSelector('.tiles .tile');
      await shot(page, `01-home${suffix}`);

      // A typed request: understood, listed, playing.
      await page.evaluate(() => H.go('home'));
      await page.fill('#ask-input', 'שעה של שירי שבת');
      await page.press('#ask-input', 'Enter');
      await page.waitForSelector('#view-results .track');
      const understood = await page.textContent('.results-title');
      if (!/שבת/.test(understood)) errors.push(`request understood as: ${understood}`);
      await page.waitForTimeout(800);
      await shot(page, `02-results${suffix}`);

      await page.evaluate(() => H.go('library'));
      await page.waitForSelector('#view-library .track');
      await shot(page, `03-library${suffix}`);

      // The song menu: why a song has its topic, and choosing another one.
      const row = page.locator('#view-library .track', { hasText: 'ניגון געגועים' }).first();
      await row.click({ button: 'right' });
      await page.waitForSelector('#track-menu:not([hidden]) .chip-choice');
      await shot(page, `10-song-menu${suffix}`);
      // (Taking a screenshot resizes the page, which closes the menu.)
      await page.locator('#view-library .track', { hasText: 'ניגון געגועים' }).first().click({ button: 'right' });
      await page.waitForSelector('#track-menu:not([hidden]) .chip-choice');
      await page.locator('#track-menu .chip-choice', { hasText: 'אמונה' }).first().click();
      await page.waitForFunction(() => {
        const r = Array.from(document.querySelectorAll('#view-library .track')).find((x) => x.textContent.includes('ניגון געגועים'));
        return r && /אמונה/.test(r.querySelector('.track-topic').textContent);
      }, null, { timeout: 10000 });
      await page.locator('#view-library .track', { hasText: 'ניגון געגועים' }).first().click({ button: 'right' });
      await page.waitForSelector('#track-menu:not([hidden])');
      const why = await page.textContent('#track-menu .menu-why');
      if (!/בחרת/.test(why)) errors.push(`song menu after a correction says: ${why}`);
      await page.locator('#track-menu .chip-choice', { hasText: 'לחזור לנושא האוטומטי' }).click();
      await page.waitForTimeout(400);

      await page.evaluate(() => H.go('topics'));
      await page.waitForSelector('#view-topics .tile');
      await shot(page, `04-topics${suffix}`);

      // Songs heard as vocal, waiting for the listener.
      await page.evaluate(() => H.openTopic('ווקאלי'));
      await page.waitForSelector('#view-results .review:not([hidden]) .review-row', { timeout: 15000 });
      await shot(page, `11-vocal-review${suffix}`);

      await page.evaluate(() => H.go('radio'));
      await page.waitForSelector('#view-radio .station, #view-radio .empty-state', { timeout: 30000 });
      await shot(page, `05-radio${suffix}`);

      await page.evaluate(() => H.go('settings'));
      await page.waitForSelector('#set-appearance');
      await shot(page, `06-settings${suffix}`);
      await page.evaluate(() => document.querySelector('#set-vocal').scrollIntoView({ block: 'start' }));
      await shot(page, `12-settings-vocal${suffix}`);

      await page.evaluate(() => H.openDrawer('queue'));
      await page.waitForSelector('#drawer .track');
      await shot(page, `07-queue${suffix}`);
      await page.evaluate(() => H.closeDrawer());

      // A song that is not on the computer: the online search panel.
      await page.evaluate(() => H.ask('תשמיע את השיר הזה שלא קיים'));
      await page.waitForSelector('#view-results .online');
      await page.waitForTimeout(2500);
      await shot(page, `08-not-found${suffix}`);

      await page.evaluate(() => H.go('downloads'));
      await page.waitForTimeout(300);
      await shot(page, `09-downloads${suffix}`);
    } catch (err) {
      errors.push(`${theme}: ${err.message}`);
      await shot(page, `error${suffix}`).catch(() => {});
    } finally {
      await app.close();
    }
  }

  const real = errors.filter((e) => !/net::ERR|Failed to load resource|kcm\.fm/.test(e));
  if (real.length) {
    console.error('UI problems:\n' + real.join('\n'));
    process.exit(1);
  }
  console.log('UI harness: all screens rendered');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
