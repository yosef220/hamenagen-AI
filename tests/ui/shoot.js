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

// "Google" for the in-window search: a page of results with a YouTube link
// behind Google's redirect, as the real one has (electron/main.js).
const http = require('http');
let searchBase = '';
const searchServer = http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end('<!doctype html><meta charset="utf-8"><title>חיפוש</title><body dir="rtl" style="font:16px Arial;padding:24px">'
    + '<h3>תוצאות</h3><a class="yt" href="https://www.google.com/url?q=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Ddemo0000001&sa=U">שיר מיוטיוב</a>'
    + '<p><a class="other" href="https://example.com/">אתר אחר</a></p></body>');
});

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
      // YouTube and song details from memory (backend/hamenagen/demo_online.py).
      HAMENAGEN_DEMO_ONLINE: '1',
      HAMENAGEN_TEST_SEARCH_BASE: searchBase,
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
  await new Promise((resolve) => searchServer.listen(0, '127.0.0.1', resolve));
  searchBase = `http://127.0.0.1:${searchServer.address().port}/search`;
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
      // Covers come from the files through cover:// (made small by the main process).
      await page.waitForFunction(() => Array.from(document.querySelectorAll('#view-library .cover img'))
        .some((img) => img.complete && img.naturalWidth > 0), null, { timeout: 15000 })
        .catch(() => errors.push('no album cover was shown in the library'));
      await shot(page, `03-library${suffix}`);

      // The song menu: why a song has its topic (a piyut from the song index)…
      await page.locator('#view-library .track', { hasText: 'בר יוחאי' }).first().click({ button: 'right' });
      await page.waitForSelector('#track-menu:not([hidden]) .chip-choice');
      const known = await page.textContent('#track-menu .menu-why');
      if (!/אינדקס השירים/.test(known)) errors.push(`song menu for a known piyut says: ${known}`);
      await shot(page, `10-song-menu${suffix}`);
      // …and choosing another topic for a song nothing could place.
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
      await page.evaluate(() => document.querySelector('#set-shabbat').scrollIntoView({ block: 'start' }));
      await page.waitForFunction(() => /הדלקת נרות/.test(document.querySelector('#set-shabbat .set-times').textContent || ''), null, { timeout: 10000 })
        .catch(() => errors.push('the Shabbat card shows no times'));
      await shot(page, `17-settings-shabbat${suffix}`);

      // Shabbat mode: the screen that covers the player until Shabbat goes out.
      await page.locator('#set-shabbat button', { hasText: 'להציג' }).click();
      await page.waitForSelector('#rest:not([hidden]) .rest-greeting');
      const greeting = await page.textContent('#rest .rest-greeting');
      if (!/שלום|חג|שנה טובה|חתימה/.test(greeting)) errors.push(`Shabbat screen says: ${greeting}`);
      await shot(page, `18-shabbat${suffix}`);
      await page.locator('#rest button', { hasText: 'חזרה' }).click();
      // The real thing: the window has begun, the player is held.
      await page.evaluate(() => H.shabbat.show(H.shabbat.status().next));
      if (!(await page.evaluate(() => H.player.blocked && !H.player.isPlaying()))) errors.push('the player is not held during Shabbat');
      await page.evaluate(() => H.shabbat.hide());

      await page.evaluate(() => H.openDrawer('queue'));
      await page.waitForSelector('#drawer .track');
      await shot(page, `07-queue${suffix}`);
      await page.evaluate(() => H.closeDrawer());

      // A song that is not on the computer: the online search panel.
      await page.evaluate(() => H.ask('תשמיע את השיר הזה שלא קיים'));
      await page.waitForSelector('#view-results .online');
      await page.waitForTimeout(2500);
      await shot(page, `08-not-found${suffix}`);

      // A singer who is not on the computer: YouTube songs and the channel.
      await page.evaluate(() => H.ask('אלי הרצליך'));
      await page.waitForSelector('#view-results .channel-card', { timeout: 15000 });
      const local = await page.$$('#view-results .tracks .track');
      if (local.length) errors.push(`a singer who is not on the computer brought ${local.length} local songs`);
      await shot(page, `13-singer-online${suffix}`);
      await page.locator('#view-results .channel-card button').click();
      await page.waitForSelector('#view-results .picker .pick');
      await page.evaluate(() => document.querySelector('#view-results .picker').scrollIntoView({ block: 'start' }));
      await shot(page, `14-channel-picker${suffix}`);

      // The network blocks searching (NetFree): say so, search in the browser, paste.
      await page.evaluate(() => H.ask('שיר שהרשת חוסמת'));
      await page.waitForSelector('#view-results .notice', { timeout: 15000 });
      await shot(page, `15-netfree${suffix}`);

      // Google inside the player's window (no window of its own): a click on
      // a YouTube result comes back to the place the search started from.
      await page.locator('#view-results button', { hasText: 'בגוגל' }).first().click();
      await page.waitForSelector('#view-websearch:not([hidden]) .websearch-frame');
      // A picture of it as the window shows it: the page lies over the frame
      // (a screenshot of the window's own page cannot see it, so it is laid in).
      const capture = await app.evaluate(async ({ webContents }) => {
        const base = process.env.HAMENAGEN_TEST_SEARCH_BASE;
        for (let i = 0; i < 100; i += 1) {
          const wc = webContents.getAllWebContents().find((w) => w.getURL().startsWith(base) && !w.isLoading());
          if (wc) {
            await new Promise((r) => setTimeout(r, 200));
            return (await wc.capturePage()).toDataURL();
          }
          await new Promise((r) => setTimeout(r, 100));
        }
        return null;
      });
      if (capture) {
        await page.evaluate((src) => {
          const img = Object.assign(document.createElement('img'), { id: 'search-capture', src });
          img.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;z-index:5';
          document.querySelector('#view-websearch .websearch-frame').appendChild(img);
        }, capture);
        await page.waitForTimeout(150);
        await shot(page, `23-google-in-window${suffix}`);
        await page.evaluate(() => document.getElementById('search-capture').remove());
      }
      const inWindow = !capture ? null : await app.evaluate(async ({ BrowserWindow, webContents }) => {
        const base = process.env.HAMENAGEN_TEST_SEARCH_BASE;
        const wc = webContents.getAllWebContents().find((w) => w.getURL().startsWith(base));
        const windows = BrowserWindow.getAllWindows().length;
        // A link to another site stays put; the YouTube one is caught.
        await wc.executeJavaScript("document.querySelector('a.other').click()");
        await new Promise((r) => setTimeout(r, 300));
        const stayed = wc.getURL().startsWith(base);
        await wc.executeJavaScript("document.querySelector('a.yt').click()");
        return { windows, stayed };
      });
      if (!inWindow) errors.push('the Google search did not open inside the window');
      else if (inWindow.windows !== 1) errors.push(`the Google search opened ${inWindow.windows - 1} more window(s)`);
      else if (!inWindow.stayed) errors.push('the Google search left Google');
      await page.waitForSelector('#view-results:not([hidden]) .link-result .online-item, #view-results:not([hidden]) .link-result .online-error', { timeout: 15000 });
      if (await page.locator('#view-websearch').isVisible()) errors.push('the Google search stayed open after the link');
      await shot(page, `24-link-from-google${suffix}`);

      // Details and a cover from the web, chosen by the listener.
      await page.evaluate(() => H.go('library'));
      await page.waitForSelector('#view-library .track');
      await page.locator('#view-library .track', { hasText: 'סביבון' }).first().click({ button: 'right' });
      await page.waitForSelector('#track-menu:not([hidden])');
      await page.locator('#track-menu .menu-item', { hasText: 'פרטים ותמונה' }).click();
      await page.waitForSelector('dialog.dialog[open] .cand', { timeout: 15000 });
      await shot(page, `16-details${suffix}`);
      await page.evaluate(() => document.querySelector('dialog.dialog').close());

      // Each song once: a copy in another folder hides behind the shown one.
      await page.evaluate(() => H.go('library'));
      await page.waitForSelector('#view-library .track');
      const copies = await page.$$eval('#view-library .track .track-title', (els) => els.filter((e) => e.textContent.trim() === 'מנוחה ושמחה').length);
      if (copies !== 1) errors.push(`a song kept in two folders shows ${copies} times`);
      await page.locator('#view-library .track', { hasText: 'מנוחה ושמחה' }).first().click({ button: 'right' });
      await page.waitForSelector('#track-menu:not([hidden]) .menu-copies', { timeout: 10000 })
        .catch(() => errors.push('the song menu does not show the other copy'));

      // Saved playlists: a new one from the song menu, more songs, a reorder.
      await page.evaluate(async () => {
        for (const p of (await H.api.playlists()).playlists) await H.api.playlistDelete(p.id);
      });
      await page.locator('#track-menu .menu-item', { hasText: 'הוספה לרשימה' }).click();
      await page.waitForSelector('dialog.dialog[open] .pl-form input');
      await page.fill('dialog.dialog[open] .pl-form input', 'שבת בבוקר');
      await page.click('dialog.dialog[open] .pl-form button[type=submit]');
      await page.waitForFunction(() => !document.querySelector('dialog.dialog[open]'));
      for (const title of ['יה ריבון', 'צור משלו', 'ידיד נפש', 'שלום עליכם']) {
        await page.locator('#view-library .track', { hasText: title }).first().click({ button: 'right' });
        await page.locator('#track-menu .menu-item', { hasText: 'הוספה לרשימה' }).click();
        await page.locator('dialog.dialog[open] .pl-choice', { hasText: 'שבת בבוקר' }).click();
        await page.waitForFunction(() => !document.querySelector('dialog.dialog[open]'));
      }
      await page.evaluate(async () => {
        const res = await H.api.ask('השירים של קול ברמה');
        await H.api.playlistCreate('קול ברמה', res.tracks.map((t) => t.id));
      });
      await page.evaluate(() => H.go('playlists'));
      await page.waitForSelector('#view-playlists .pl-card');
      await page.waitForTimeout(600);
      await shot(page, `19-playlists${suffix}`);
      await page.locator('#view-playlists .pl-card', { hasText: 'שבת בבוקר' }).click();
      await page.waitForSelector('#view-playlists .pl-row');
      const firstTitle = (await page.textContent('#view-playlists .pl-row .track-title')).trim();
      await page.focus('#view-playlists .pl-row');
      await page.keyboard.press('Alt+ArrowDown');
      await page.waitForTimeout(400);
      const saved = await page.evaluate(async () => {
        const { playlists } = await H.api.playlists();
        const p = playlists.find((x) => x.name === 'שבת בבוקר');
        return (await H.api.playlistGet(p.id)).tracks.map((t) => t.title);
      });
      if (saved.length !== 5 || saved[1] !== firstTitle) errors.push(`playlist order after a move: ${saved.join(', ')}`);
      await shot(page, `20-playlist${suffix}`);

      // A set for an occasion: the brit's songs from the library, and YouTube
      // in the listener's style, to play without saving.
      await page.evaluate(() => H.ask('תפעיל לי סט שירים לברית'));
      await page.waitForSelector('#view-results .set-online .online-item', { timeout: 15000 });
      const setTitle = await page.textContent('.results-title');
      if (!/סט לברית/.test(setTitle)) errors.push(`a set request understood as: ${setTitle}`);
      await shot(page, `21-set-brit${suffix}`);
      await page.locator('#view-results .set-online .results-actions .btn-primary').click();
      await page.waitForFunction(() => H.player.isPlaying(), null, { timeout: 15000 })
        .catch(() => errors.push('the set did not start playing'));
      await page.evaluate(() => { const P = H.player; P.jump(P.queue.findIndex((t) => t.listen)); });
      await page.waitForFunction(() => { const c = H.player.current(); return c && c.listen && c.path && H.player.isPlaying(); }, null, { timeout: 20000 })
        .catch(() => errors.push('a song from YouTube did not play without saving'));
      await page.waitForTimeout(500);
      await shot(page, `22-listening${suffix}`);
      await page.evaluate(() => H.player.toggle(false));

      // A soft transition: near the end of a song, the next one comes in.
      const crossfaded = await page.evaluate(async () => {
        const P = H.player;
        const { tracks } = await H.api.ask('שירי חנוכה');
        P.playList(tracks.slice(0, 2), 0, { crossfade: 4 });
        await new Promise((r) => setTimeout(r, 800));
        P.seekTo(P.audio.duration - 5);
        await new Promise((r) => setTimeout(r, 2500));
        const handed = P.index === 1 && P.isPlaying();
        P.toggle(false);
        return handed;
      });
      if (!crossfaded) errors.push('the crossfade did not move on to the next song');

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

  searchServer.close();
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
