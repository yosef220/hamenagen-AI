'use strict';

/**
 * Bridge between the Electron main process and the Python core.
 *
 * Spawns `python -m hamenagen.rpc` and speaks the newline-delimited JSON-RPC
 * protocol defined in backend/hamenagen/rpc.py. Requests are correlated by a
 * monotonically increasing id; responses resolve the matching promise.
 *
 * No network socket is opened — everything goes over the child's stdio — which
 * keeps the app portable and avoids firewall prompts on the user's machine.
 */

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

/**
 * Resolve which Python interpreter to run and where the backend lives.
 *
 * In a packaged build, electron-builder copies `backend/` into
 * `process.resourcesPath/backend` (see package.json build.extraResources), and
 * an embedded CPython may be bundled at `resources/python/python(.exe)`. In dev
 * we just use the repo's `backend/` and the system `python`.
 */
function resolveBackend(options) {
  const packagedResources = process.resourcesPath || '';
  const packagedBackend = path.join(packagedResources, 'backend');
  const isPackaged = fs.existsSync(packagedBackend);
  const backendDir = options.backendDir || (isPackaged ? packagedBackend : path.join(__dirname, '..', 'backend'));

  if (options.pythonPath || process.env.HAMENAGEN_PYTHON) {
    return { pythonPath: options.pythonPath || process.env.HAMENAGEN_PYTHON, backendDir };
  }
  if (isPackaged) {
    const exe = process.platform === 'win32' ? 'python.exe' : 'python';
    for (const candidate of [
      path.join(packagedResources, 'python', exe),
      path.join(packagedResources, 'python', 'bin', exe),
    ]) {
      if (fs.existsSync(candidate)) return { pythonPath: candidate, backendDir };
    }
  }
  // Fall back to system Python on PATH.
  return { pythonPath: process.platform === 'win32' ? 'python.exe' : 'python3', backendDir };
}

class BackendBridge {
  constructor(options = {}) {
    const resolved = resolveBackend(options);
    this.pythonPath = resolved.pythonPath;
    this.backendDir = resolved.backendDir;
    this.proc = null;
    this.rl = null;
    this._nextId = 1;
    this._pending = new Map();
    this._eventHandlers = new Set();
  }

  /** Register a handler for out-of-band backend events (e.g. progress). */
  onEvent(handler) {
    this._eventHandlers.add(handler);
    return () => this._eventHandlers.delete(handler);
  }

  start() {
    if (this.proc) return;
    // The Windows *embeddable* Python uses a ._pth file that fully defines
    // sys.path and ignores the CWD and PYTHONPATH — so `-m hamenagen.rpc`
    // can't find the package and the process exits with code 1. Bootstrap the
    // path explicitly at runtime (works for both embedded and system Python).
    const bootstrap =
      "import os, sys; sys.path.insert(0, os.environ.get('HAMENAGEN_BACKEND_DIR', '')); " +
      'from hamenagen.rpc import main; main()';
    this.proc = spawn(this.pythonPath, ['-c', bootstrap], {
      cwd: this.backendDir,
      env: {
        ...process.env,
        HAMENAGEN_BACKEND_DIR: this.backendDir,
        PYTHONUNBUFFERED: '1',
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
      },
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    this.rl = readline.createInterface({ input: this.proc.stdout });
    this.rl.on('line', (line) => this._onLine(line));

    this.proc.stderr.on('data', (d) => {
      // Surface backend diagnostics to the terminal without crashing the UI.
      process.stderr.write(`[backend] ${d}`);
    });

    this.proc.on('exit', (code) => {
      const err = new Error(`backend exited (code ${code})`);
      for (const { reject } of this._pending.values()) reject(err);
      this._pending.clear();
      this.proc = null;
    });
  }

  _onLine(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return; // ignore non-JSON noise
    }
    // Out-of-band notifications carry an "event" field and no response id.
    if (msg.event) {
      for (const h of this._eventHandlers) {
        try { h(msg); } catch { /* handler errors must not kill the reader */ }
      }
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
    const id = this._nextId++;
    const payload = JSON.stringify({ id, method, params }) + '\n';
    return new Promise((resolve, reject) => {
      this._pending.set(id, { resolve, reject });
      this.proc.stdin.write(payload);
    });
  }

  stop() {
    if (this.proc) {
      try { this.proc.stdin.end(); } catch { /* ignore */ }
      this.proc.kill();
      this.proc = null;
    }
  }
}

module.exports = { BackendBridge };
