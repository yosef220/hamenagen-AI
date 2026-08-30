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
const path = require('path');
const readline = require('readline');

class BackendBridge {
  constructor(options = {}) {
    this.pythonPath = options.pythonPath || process.env.HAMENAGEN_PYTHON || 'python';
    this.backendDir = options.backendDir || path.join(__dirname, '..', 'backend');
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
    this.proc = spawn(this.pythonPath, ['-m', 'hamenagen.rpc'], {
      cwd: this.backendDir,
      env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
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
