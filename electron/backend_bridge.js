'use strict';

/**
 * Bridge between the Electron main process and the Python core.
 *
 * Spawns the core (backend/hamenagen/rpc.py) and speaks its newline-delimited
 * JSON-RPC protocol over stdio. Requests are correlated by a monotonically
 * increasing id, so responses may arrive in any order (slow requests are
 * answered from worker threads). Lines without an id are events (progress,
 * "ready") and go to the registered event handlers.
 *
 * No network socket is opened — everything goes over the child's stdio — which
 * keeps the app portable and avoids firewall prompts on the user's machine.
 */

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const STDERR_TAIL = 8 * 1024;
const LOG_LIMIT = 1024 * 1024;

/**
 * Resolve which Python interpreter to run and where the backend lives.
 *
 * In a packaged build, electron-builder copies `backend/` into
 * `resources/backend` and the embedded CPython into `resources/python`
 * (package.json build.extraResources). In development the repo's `backend/`
 * and the system Python are used.
 */
function resolveBackend(options = {}) {
  const resources = process.resourcesPath || '';
  const packagedBackend = path.join(resources, 'backend');
  const isPackaged = fs.existsSync(packagedBackend);
  const backendDir =
    options.backendDir || (isPackaged ? packagedBackend : path.join(__dirname, '..', 'backend'));

  if (options.pythonPath || process.env.HAMENAGEN_PYTHON) {
    return { pythonPath: options.pythonPath || process.env.HAMENAGEN_PYTHON, backendDir };
  }
  if (isPackaged) {
    const exe = process.platform === 'win32' ? 'python.exe' : 'python';
    for (const candidate of [
      path.join(resources, 'python', exe),
      path.join(resources, 'python', 'bin', exe),
    ]) {
      if (fs.existsSync(candidate)) return { pythonPath: candidate, backendDir };
    }
  }
  return { pythonPath: process.platform === 'win32' ? 'python.exe' : 'python3', backendDir };
}

class BackendBridge {
  /**
   * @param {object} options
   * @param {object} [options.env]      extra environment for the core
   * @param {string} [options.logFile]  where to keep the core's diagnostics
   */
  constructor(options = {}) {
    const resolved = resolveBackend(options);
    this.pythonPath = resolved.pythonPath;
    this.backendDir = resolved.backendDir;
    this.extraEnv = options.env || {};
    this.logFile = options.logFile || null;
    this.proc = null;
    this.rl = null;
    this.ready = false;
    this.stopping = false;
    this.restarts = 0;
    this._stderr = '';
    this._nextId = 1;
    this._pending = new Map();
    this._eventHandlers = new Set();
  }

  /** Register a handler for out-of-band backend events (progress, ready …). */
  onEvent(handler) {
    this._eventHandlers.add(handler);
    return () => this._eventHandlers.delete(handler);
  }

  _broadcast(msg) {
    for (const h of this._eventHandlers) {
      try { h(msg); } catch { /* a handler must not kill the reader */ }
    }
  }

  _log(text) {
    if (!this.logFile) return;
    try {
      fs.mkdirSync(path.dirname(this.logFile), { recursive: true });
      if (fs.existsSync(this.logFile) && fs.statSync(this.logFile).size > LOG_LIMIT) {
        fs.renameSync(this.logFile, this.logFile + '.old');
      }
      fs.appendFileSync(this.logFile, text);
    } catch { /* logging is best effort */ }
  }

  start() {
    if (this.proc) return;
    this.ready = false;
    this.stopping = false;
    // The Windows *embeddable* Python uses a ._pth file that fully defines
    // sys.path and ignores the CWD and PYTHONPATH — so `-m hamenagen.rpc`
    // cannot find the package. Bootstrap the path explicitly at runtime
    // (works for both the embedded and a system Python).
    const bootstrap =
      "import os, sys; sys.path.insert(0, os.environ.get('HAMENAGEN_BACKEND_DIR', '')); " +
      'from hamenagen.rpc import main; main()';
    this._log(`\n=== ${new Date().toISOString()} start ${this.pythonPath}\n`);
    let proc;
    try {
      proc = spawn(this.pythonPath, ['-c', bootstrap], {
        cwd: this.backendDir,
        env: {
          ...process.env,
          ...this.extraEnv,
          HAMENAGEN_BACKEND_DIR: this.backendDir,
          PYTHONUNBUFFERED: '1',
          PYTHONIOENCODING: 'utf-8',
          PYTHONUTF8: '1',
          PYTHONDONTWRITEBYTECODE: '1',
        },
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      });
    } catch (err) {
      this._broadcast({ event: 'backend_failed', code: null, stderr: String(err) });
      return;
    }
    this.proc = proc;

    this.rl = readline.createInterface({ input: proc.stdout });
    this.rl.on('line', (line) => this._onLine(line));

    proc.stderr.on('data', (d) => {
      const text = d.toString();
      this._stderr = (this._stderr + text).slice(-STDERR_TAIL);
      this._log(text);
      if (!process.env.HAMENAGEN_QUIET) process.stderr.write(`[backend] ${text}`);
    });

    proc.on('error', (err) => {
      // e.g. ENOENT: no Python found. Reported once as a failure.
      this._stderr += `\n${err.message}`;
    });

    proc.on('exit', (code) => {
      const wasReady = this.ready;
      const err = new Error(`backend exited (code ${code})`);
      for (const { reject } of this._pending.values()) reject(err);
      this._pending.clear();
      this.proc = null;
      this.ready = false;
      this._log(`=== exit ${code}\n`);
      if (this.stopping) return;
      if (wasReady && this.restarts < 3) {
        // A crash after a good start: come back quietly; the UI reloads state.
        this.restarts += 1;
        this._broadcast({ event: 'backend_restarting', code });
        setTimeout(() => this.start(), 400);
      } else {
        this._broadcast({ event: 'backend_failed', code, stderr: this._stderr.slice(-4000) });
      }
    });
  }

  _onLine(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return; // ignore non-JSON noise
    }
    if (msg.event) {
      if (msg.event === 'ready') this.ready = true;
      this._broadcast(msg);
      return;
    }
    const entry = this._pending.get(msg.id);
    if (!entry) return;
    this._pending.delete(msg.id);
    if (msg.ok) entry.resolve(msg.result);
    else entry.reject(new Error(msg.error || 'backend error'));
  }

  call(method, params = {}) {
    this.start();
    if (!this.proc) return Promise.reject(new Error('backend unavailable'));
    const id = this._nextId++;
    const payload = JSON.stringify({ id, method, params }) + '\n';
    return new Promise((resolve, reject) => {
      this._pending.set(id, { resolve, reject });
      try {
        this.proc.stdin.write(payload);
      } catch (err) {
        this._pending.delete(id);
        reject(err);
      }
    });
  }

  stop() {
    this.stopping = true;
    if (this.proc) {
      try { this.proc.stdin.end(); } catch { /* ignore */ }
      const proc = this.proc;
      setTimeout(() => { try { proc.kill(); } catch { /* ignore */ } }, 600);
      this.proc = null;
    }
  }
}

module.exports = { BackendBridge, resolveBackend };
