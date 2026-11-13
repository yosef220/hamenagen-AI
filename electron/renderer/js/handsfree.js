'use strict';

/*
 * Hands-free (1.5.1): while the player is in front, the microphone listens
 * all the time for spoken commands, so the listener can say "הבא", "תנמיך",
 * "תגביר", "עצור" from across the room without touching the computer.
 *
 *  - Only commands work by themselves. A request ("שירי שבת") starts with the
 *    player's name: "המנגן, תשמיע שירי שבת". Everything else that is heard
 *    (people talking, the songs themselves) is ignored and kept nowhere.
 *  - In front (electron/main.js): the window has the focus, or had it when
 *    the computer went idle, locked or blanked the screen. Minimized, hidden
 *    or behind a program in use: no listening, the mic button works as before.
 *  - Never on Shabbat and holidays (the Shabbat screen), never while the mic
 *    button is in use, and never without the listener's speech model
 *    (73MB, downloaded only after asking).
 *  - The recognizer runs only on stretches that sound like speech (a level
 *    above the room's noise), with the browser's echo cancellation removing
 *    most of the music the player itself plays.
 *  - Can be turned off in the settings (בקשה בקול).
 */
(function () {
  const { h, icon, api } = H;
  const RATE = 16000;
  const FRAME_MS = 50;
  const START_DB = 9;           // above the noise floor: speech begins
  const START_MS = 150;         // …for at least this long
  const END_MS = 750;           // quiet this long: the sentence ended
  const MAX_MS = 6000;          // the longest command
  const PREROLL_MS = 350;       // keep a little from before the start
  const WAKE = /^(?:היי |הי |הלו )?ה?מנגן(?:[ ,]+|$)/;

  const F = { on: false, front: false, model: false, power: '', forced: null };
  let rig = null;               // { stream, ctx, timer, … } while listening
  let offered = false;
  let busy = false;

  const wanted = () => {
    const s = H.settings || {};
    const front = F.forced !== null ? F.forced : F.front;
    return s.hands_free !== false && front && F.model && !document.hidden
      && !(H.shabbat && H.shabbat.shown && H.shabbat.shown())
      && !(H.voice && H.voice.state !== 'idle');
  };

  async function sync() {
    if (busy) return;
    busy = true;
    try {
      if (wanted() && !rig) await start();
      else if (!wanted() && rig) stop();
    } finally {
      busy = false;
    }
    showState();
  }

  function showState() {
    document.body.classList.toggle('hands-free', !!rig);
    for (const b of document.querySelectorAll('.mic-btn')) {
      b.classList.toggle('standby', !!rig);
      if (rig && (!H.voice || H.voice.state === 'idle')) b.title = 'מקשיב לפקודות: „הבא”, „תנמיך”… או „המנגן, …” לבקשה. לחיצה: בקשה רגילה';
    }
  }

  // ------------------------------------------------------------ the microphone
  async function start() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      return;      // no microphone, or not allowed: the button still says why
    }
    if (!wanted()) { for (const t of stream.getTracks()) t.stop(); return; }
    const ctx = new AudioContext({ sampleRate: RATE });
    const source = ctx.createMediaStreamSource(stream);
    const tap = ctx.createScriptProcessor(1024, 1, 1);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    source.connect(tap);
    tap.connect(mute);
    mute.connect(ctx.destination);

    const pre = [];               // the last few frames, before speech starts
    let take = null;              // frames of the sentence being spoken
    let floor = null;
    let loudFor = 0;
    let quietFor = 0;
    let takeMs = 0;
    const frameMs = (1024 / RATE) * 1000;

    tap.onaudioprocess = (e) => {
      const x = new Float32Array(e.inputBuffer.getChannelData(0));
      let sum = 0;
      for (let i = 0; i < x.length; i += 1) sum += x[i] * x[i];
      const db = 10 * Math.log10(sum / x.length + 1e-12);
      // The room's level: follows quiet stretches quickly, loud ones slowly.
      if (floor === null) floor = db;
      else if (db < floor) floor = floor * 0.7 + db * 0.3;
      else if (!take) floor = floor * 0.995 + db * 0.005;
      const loud = db > Math.max(-52, floor + START_DB);
      if (!take) {
        pre.push(x);
        while (pre.length * frameMs > PREROLL_MS) pre.shift();
        loudFor = loud ? loudFor + frameMs : 0;
        if (loudFor >= START_MS) { take = pre.splice(0); takeMs = take.length * frameMs; quietFor = 0; }
        return;
      }
      take.push(x);
      takeMs += frameMs;
      quietFor = loud ? 0 : quietFor + frameMs;
      if (quietFor >= END_MS || takeMs >= MAX_MS) {
        const done = take;
        take = null;
        loudFor = 0;
        if (takeMs - quietFor >= 250) heard(done);
      }
    };
    rig = { stream, ctx, tap };
  }

  function stop() {
    if (!rig) return;
    rig.tap.onaudioprocess = null;
    for (const t of rig.stream.getTracks()) t.stop();
    rig.ctx.close().catch(() => {});
    rig = null;
  }

  function toBase64(parts) {
    let n = 0;
    for (const a of parts) n += a.length;
    const pcm = new Int16Array(n);
    let o = 0;
    for (const a of parts) {
      for (let i = 0; i < a.length; i += 1) pcm[o + i] = Math.max(-1, Math.min(1, a[i])) * 32767;
      o += a.length;
    }
    const bytes = new Uint8Array(pcm.buffer);
    let out = '';
    for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(out);
  }

  let thinking = false;
  async function heard(parts) {
    if (thinking) return;           // one sentence at a time
    thinking = true;
    try {
      const res = await api.voiceRecognize(toBase64(parts), RATE);
      if (res && res.ok && res.request) F.handle(res.request);
    } catch { /* the next sentence */ }
    thinking = false;
  }

  // ------------------------------------------------------------ what was said
  /** Act on a sentence heard without a click. Returns what was done. */
  F.handle = function handle(text) {
    const t = String(text || '').trim();
    api.emit('handsfree-heard', { text: t });
    const wake = t.match(WAKE);
    if (wake) {
      const rest = t.slice(wake[0].length).trim();
      if (!rest) { H.toast('כן? אפשר לבקש, למשל: „המנגן, תשמיע שירי שבת”', { icon: 'mic' }); return 'wake'; }
      if (H.voice.command(rest)) return 'command';
      api.emit('voice-heard', { text: rest });
      H.ask(rest, { spoken: true });
      return 'request';
    }
    // Without the name, only commands that cannot be a word in a song.
    if (H.voice.commandFor(t, { strict: true }) && H.voice.command(t)) return 'command';
    return null;
  };

  // ------------------------------------------------------------ the speech model
  function offerModel() {
    if (offered || H.$('#voice-model-offer')) return;
    offered = true;
    const bar = h('div', { class: 'update-bar', id: 'voice-model-offer', role: 'region', 'aria-label': 'הקשבה לפקודות' },
      icon('mic'),
      h('span', { class: 'model-offer-text' },
        'המנגן יכול לשמוע אותך בלי לחיצה כשהוא בחזית: „הבא”, „תנמיך”, „המנגן, תשמיע שירי שבת”. ',
        'לזה צריך את מודל הדיבור בעברית (73MB, פעם אחת). הזיהוי נעשה במחשב, ושום הקלטה לא נשמרת או נשלחת.'),
      h('button', { class: 'btn btn-quiet', type: 'button', onclick: async () => {
        bar.remove();
        const off = api.on('voice_install', (msg) => {
          if (msg.status === 'done') { off(); F.model = true; H.toast('אפשר לדבר: „הבא”, „תנמיך”, „המנגן, …”', { icon: 'mic' }); sync(); }
          else if (msg.status === 'error') { off(); H.toast(msg.message || 'ההורדה לא הצליחה', { kind: 'bad' }); }
        });
        const r = await api.installVoice().catch((err) => ({ started: false, reason: err.message }));
        if (!r.started && r.reason === 'already installed') { off(); F.model = true; sync(); }
      } }, 'להוריד'),
      h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => bar.remove() }, 'לא עכשיו'),
      h('button', { class: 'btn btn-quiet', type: 'button', onclick: async () => {
        bar.remove();
        try { H.settings = await api.updateSettings({ hands_free: false }); } catch { /* this run only */ }
        sync();
      } }, 'לכבות'));
    const main = H.$('#main');
    main.insertBefore(bar, main.firstChild);
  }

  async function checkModel() {
    try {
      const st = await api.voiceStatus();
      F.model = !!st.available;
      if (F.model && !st.loaded && F.front) api.voicePrepare().catch(() => {});
      if (!F.model && (H.settings || {}).hands_free !== false && F.front) offerModel();
    } catch { F.model = false; }
  }

  // ------------------------------------------------------------ when to listen
  api.on('front', ({ front }) => {
    F.front = !!front;
    if (F.front && !F.model) checkModel().then(sync);
    else sync();
  });
  api.on('power', ({ event }) => {
    F.power = event;
    if (event === 'resume' && rig) { stop(); sync(); }   // the device may have changed while asleep
  });
  api.on('voice-state', () => sync());
  document.addEventListener('visibilitychange', () => sync());
  setInterval(sync, 3000);            // the Shabbat screen, the settings

  F.refresh = async () => { await checkModel(); return sync(); };
  F.setFront = (value) => { F.forced = value; return sync(); };   // the UI harness
  F.listening = () => !!rig;
  H.handsFree = F;

  window.addEventListener('load', async () => {
    try { F.front = await api.isFront(); } catch { F.front = document.hasFocus(); }
    setTimeout(F.refresh, 1500);       // after the settings are in
  });
})();
