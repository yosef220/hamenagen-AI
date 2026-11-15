'use strict';

/**
 * The search window in Edge's engine (1.5.9): backend/hamenagen/searchwin.py, a WebView2 window through
 * pywebview — the way the download-from-YouTube program shows Google, where the results look right —
 * owned by the player's window and laid over the search's place in it. This side starts the process,
 * sends it where to stand and what to open, and hands its events (a YouTube link, Esc, a blocked page) on.
 *
 * Windows only. When it cannot start (no WebView2 runtime, no pythonnet), `start()` fails and the player
 * keeps using its own (Electron) view.
 */

const { spawn } = require('child_process');
const os = require('os');
const readline = require('readline');

class NativeSearch {
  /**
   * @param {object} o
   * @param {string} o.pythonPath
   * @param {string} o.backendDir
   * @param {string} o.profileDir  WebView2's profile (cookies, as in a browser)
   * @param {(event: object) => void} o.onEvent
   * @param {(line: string) => void} [o.log]
   */
  constructor(o) {
    this.o = o;
    this.proc = null;
    this.readyPromise = null;
    this.failed = false;
  }

  /** Starts the window process once; resolves when it is ready, rejects when it cannot be. */
  start(ownerHwnd) {
    if (this.failed) return Promise.reject(new Error('the WebView2 window could not start before'));
    if (this.readyPromise) return this.readyPromise;
    const bootstrap = "import os, sys; sys.path.insert(0, os.environ.get('HAMENAGEN_BACKEND_DIR', '')); "
      + 'from hamenagen.searchwin import main; sys.exit(main())';
    this.readyPromise = new Promise((resolve, reject) => {
      let settled = false;
      const fail = (why) => {
        if (settled) return;
        settled = true;
        this.failed = true;
        this.stop();
        reject(new Error(why));
      };
      let proc;
      try {
        proc = spawn(this.o.pythonPath, ['-c', bootstrap, '--owner', String(ownerHwnd), '--profile', this.o.profileDir], {
          cwd: os.tmpdir(),
          env: {
            ...process.env,
            HAMENAGEN_BACKEND_DIR: this.o.backendDir,
            PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1',
          },
          stdio: ['pipe', 'pipe', 'pipe'],
          windowsHide: true,
        });
      } catch (err) {
        fail(err.message);
        return;
      }
      this.proc = proc;
      const timer = setTimeout(() => fail('the WebView2 window did not answer in 25 seconds'), 25000);
      readline.createInterface({ input: proc.stdout }).on('line', (line) => {
        let msg;
        try { msg = JSON.parse(line); } catch { return; }
        if (this.o.log) this.o.log(`searchwin: ${line}`);
        if (msg.event === 'ready' && !settled) {
          settled = true;
          clearTimeout(timer);
          resolve();
          return;
        }
        if (msg.event === 'error' && !settled) {
          clearTimeout(timer);
          fail(msg.message || 'error');
          return;
        }
        this.o.onEvent(msg);
      });
      proc.stderr.on('data', (d) => { if (this.o.log) this.o.log(`searchwin stderr: ${d}`); });
      proc.on('exit', (code) => {
        clearTimeout(timer);
        this.proc = null;
        if (!settled) fail(`the WebView2 window exited (${code})`);
        else this.readyPromise = null;          // it may start again on the next search
        this.o.onEvent({ event: 'exit', code });
      });
      proc.on('error', (err) => { clearTimeout(timer); fail(err.message); });
    });
    return this.readyPromise;
  }

  send(msg) {
    if (!this.proc || !this.proc.stdin.writable) return false;
    this.proc.stdin.write(`${JSON.stringify(msg)}\n`);
    return true;
  }

  open(url, rect) { return this.send({ cmd: 'open', url, rect }); }

  place(rect) { return this.send({ cmd: 'place', rect }); }

  hide() { return this.send({ cmd: 'hide' }); }

  nav(action) { return this.send({ cmd: 'nav', action }); }

  stop() {
    if (!this.proc) return;
    this.send({ cmd: 'quit' });
    const p = this.proc;
    setTimeout(() => { try { p.kill(); } catch { /* gone */ } }, 1500);
  }
}

module.exports = { NativeSearch };
