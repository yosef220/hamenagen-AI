'use strict';

/* Requests by voice (1.4).

   The microphone button beside the request line records what is said,
   stops by itself after a short pause, and sends the sound to the core,
   which recognizes the Hebrew speech on this computer (voice.py, ivrit.ai's
   model) — no internet and no browser service. The words go into the
   request line and are played like a typed request.

   The music steps back while listening (H.player.duck), so the speakers do
   not talk over the speaker. */
(function () {
  const { h, icon, api } = H;
  const RATE = 16000;
  const MAX_MS = 9000;          // the longest request
  const QUIET_MS = 1100;        // a pause this long after speech ends it
  const NOTHING_MS = 5000;      // no speech at all: give up

  const V = { state: 'idle' };  // idle | preparing | listening | thinking
  H.voice = V;
  const buttons = new Set();
  let session = null;

  function setState(state, extra = {}) {
    V.state = state;
    for (const b of buttons) {
      b.dataset.state = state;
      b.setAttribute('aria-pressed', state === 'listening' ? 'true' : 'false');
      b.setAttribute('aria-label', state === 'listening' ? 'לסיים ולשלוח' : state === 'thinking' ? 'מזהה את הבקשה…' : 'בקשה בקול');
      b.title = b.getAttribute('aria-label');
      H.setIcon(b, state === 'listening' ? 'square' : state === 'thinking' || state === 'preparing' ? 'loader-circle' : 'mic');
      b.disabled = state === 'thinking' || state === 'preparing';
    }
    api.emit('voice-state', { state, ...extra });
  }

  // ------------------------------------------------------------ the model
  async function ensureModel() {
    const st = await api.voiceStatus();
    if (st.available) {
      if (!st.loaded) api.voicePrepare().catch(() => {});   // loads while the listener speaks
      return true;
    }
    // The editions without the model download it once (73 MB), on request.
    return new Promise((resolve) => {
      const offer = h('div', { class: 'voice-offer', role: 'dialog', 'aria-label': 'הורדת זיהוי הדיבור' },
        icon('mic', 'icon-sm'),
        h('div', { class: 'voice-offer-text' },
          h('strong', {}, 'זיהוי דיבור בעברית, בלי אינטרנט'),
          h('span', {}, `בפעם הראשונה צריך להוריד את המודל (${st.download_mb || 73}MB, של ivrit.ai). אחר כך הוא עובד גם בלי חיבור.`)),
        h('div', { class: 'voice-offer-actions' }));
      const actions = offer.querySelector('.voice-offer-actions');
      const bar = h('div', { class: 'voice-progress', hidden: true }, h('span', {}));
      offer.querySelector('.voice-offer-text').append(bar);
      const done = (ok) => { off(); offer.remove(); resolve(ok); };
      const off = api.on('voice_install', (msg) => {
        if (msg.status === 'downloading') {
          bar.hidden = false;
          bar.firstChild.style.width = `${msg.percent || 0}%`;
        } else if (msg.status === 'done') {
          H.toast('זיהוי הדיבור מוכן. אפשר לדבר.', { icon: 'mic' });
          done(true);
        } else {
          H.toast(msg.message || msg.error || 'ההורדה לא הצליחה', { kind: 'bad' });
          done(false);
        }
      });
      actions.append(
        h('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: async (e) => {
          e.currentTarget.disabled = true;
          const r = await api.installVoice().catch((err) => ({ started: false, reason: err.message }));
          if (!r.started && r.reason !== 'already running') {
            if (r.reason === 'already installed') done(true);
            else { H.toast(r.reason || 'ההורדה לא התחילה', { kind: 'bad' }); done(false); }
          }
        } }, icon('cloud-download', 'icon-sm'), 'להוריד'),
        h('button', { class: 'btn btn-quiet btn-sm', type: 'button', onclick: () => done(false) }, 'לא עכשיו'));
      const host = H.$('.ask') || document.body;
      host.append(offer);
    });
  }

  // ------------------------------------------------------------ recording
  function toBase64(int16) {
    const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
    let out = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(out);
  }

  // The take so far, as 16-bit samples.
  function toPcm(parts) {
    let n = 0;
    for (const a of parts) n += a.length;
    const pcm = new Int16Array(n);
    let o = 0;
    for (const a of parts) {
      for (let i = 0; i < a.length; i += 1) pcm[o + i] = Math.max(-1, Math.min(1, a[i])) * 32767;
      o += a.length;
    }
    return pcm;
  }

  async function listen() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (err) {
      H.toast(err && err.name === 'NotFoundError' ? 'לא נמצא מיקרופון במחשב' : 'אין גישה למיקרופון. אפשר לבדוק בהגדרות הפרטיות של Windows שמותר לאפליקציות להשתמש במיקרופון.', { kind: 'bad', icon: 'mic-off' });
      setState('idle');
      return;
    }
    // The sound itself, at 16 kHz (the browser resamples the microphone), so
    // nothing has to be encoded and decoded again.
    const ctx = new AudioContext({ sampleRate: RATE });
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    const tap = ctx.createScriptProcessor(4096, 1, 1);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    const parts = [];
    let recording = true;
    tap.onaudioprocess = (e) => { if (recording) parts.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
    source.connect(analyser);
    source.connect(tap);
    tap.connect(mute);
    mute.connect(ctx.destination);
    const buf = new Float32Array(analyser.fftSize);

    const started = performance.now();
    let floor = null;
    let heard = false;
    let lastLoud = started;
    let cancelled = false;
    let done;
    const finished = new Promise((resolve) => { done = resolve; });

    const stop = (cancel = false) => {
      cancelled = cancelled || cancel;
      clearInterval(timer);
      if (recording) { recording = false; done(); }
    };
    session = { stop };
    const timer = setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i += 1) sum += buf[i] * buf[i];
      const db = 10 * Math.log10(sum / buf.length + 1e-12);
      const now = performance.now();
      if (floor === null || (!heard && now - started < 400)) floor = floor === null ? db : Math.min(floor, db);
      const loud = db > Math.max(-48, floor + 12);
      if (loud) { heard = true; lastLoud = now; }
      api.emit('voice-level', { level: Math.max(0, Math.min(1, (db + 60) / 45)) });
      if (now - started > MAX_MS || (heard && now - lastLoud > QUIET_MS)) stop();
      else if (!heard && now - started > NOTHING_MS) stop(true);
    }, 50);

    // Live text: what was heard so far, every second while speaking (the
    // recognizer takes a fraction of a second, so the whole take is sent).
    let partialBusy = false;
    const partial = setInterval(async () => {
      if (!heard || partialBusy || !recording || !parts.length) return;
      partialBusy = true;
      try {
        const res = await api.voiceRecognize(toBase64(toPcm(parts)), ctx.sampleRate);
        if (V.state === 'listening' && recording && res.ok && res.request) api.emit('voice-partial', { text: res.request });
      } catch { /* the final pass will tell */ }
      partialBusy = false;
    }, 700);

    H.player.duck(true);
    setState('listening');
    await finished;
    clearInterval(partial);
    session = null;
    H.player.duck(false);
    for (const t of stream.getTracks()) t.stop();
    tap.onaudioprocess = null;
    ctx.close().catch(() => {});

    if (cancelled || !heard) {
      setState('idle');
      if (!heard) H.toast('לא שמעתי כלום. אפשר ללחוץ שוב ולדבר קרוב יותר למיקרופון.', { icon: 'mic-off' });
      return;
    }
    setState('thinking');
    try {
      const res = await api.voiceRecognize(toBase64(toPcm(parts)), ctx.sampleRate);
      setState('idle');
      if (!res.ok) {
        H.toast(res.message || 'הזיהוי לא הצליח', { kind: 'bad' });
        return;
      }
      if (!res.request) {
        H.toast('לא הצלחתי להבין את הבקשה. אפשר לנסות שוב.', { icon: 'mic-off' });
        return;
      }
      if (V.command(res.request)) { api.emit('voice-partial', { text: '' }); return; }
      api.emit('voice-heard', { text: res.request });
      H.ask(res.request, { spoken: true });
    } catch (err) {
      setState('idle');
      H.toast(`הזיהוי לא הצליח: ${err.message}`, { kind: 'bad' });
    }
  }

  // ------------------------------------------------------------ commands
  // Short spoken commands work the player instead of being searched for.
  // Only the whole sentence counts ("הבא", "תגביר בבקשה"), so a song whose
  // name holds such a word is still found.
  const POLITE = /(^| )(בבקשה|לי|את|השיר|המוזיקה|מוזיקה|קצת|עוד)(?= |$)/g;
  const COMMANDS = [
    ['next', ['הבא', 'שיר הבא', 'לשיר הבא', 'לבא', 'תעביר', 'תעביר הלאה', 'הלאה', 'דלג', 'תדלג', 'next',
      'שיר אחר', 'משהו אחר', 'תחליף', 'תחליף שיר', 'החלף', 'החלף שיר', 'הבא בתור']],
    ['prev', ['הקודם', 'שיר קודם', 'לשיר הקודם', 'לקודם', 'תחזור', 'אחורה', 'שוב', 'אחד אחורה', 'שיר אחורה']],
    ['pause', ['עצור', 'תעצור', 'הפסק', 'תפסיק', 'השהה', 'stop', 'pause', 'תשתיק', 'השתק', 'די', 'מספיק', 'שקט',
      'תעצור הכל', 'לעצור', 'להפסיק']],
    ['play', ['המשך', 'תמשיך', 'נגן', 'תנגן', 'play', 'תמשיך לנגן', 'להמשיך', 'תחזיר המוזיקה']],
    ['louder', ['תגביר', 'הגבר', 'להגביר', 'יותר חזק', 'חזק יותר', 'תגביר הווליום', 'תגביר העוצמה', 'תרים',
      'תרים הווליום', 'תרים העוצמה', 'יותר בקול', 'יותר רועש', 'חזק', 'תגביר טיפה']],
    ['quieter', ['תנמיך', 'הנמך', 'להנמיך', 'יותר חלש', 'חלש יותר', 'יותר בשקט', 'תנמיך הווליום', 'תנמיך העוצמה',
      'תוריד הווליום', 'תוריד העוצמה', 'תוריד הקול', 'חלש', 'תנמיך טיפה']],
    ['shuffle', ['ערבב', 'תערבב', 'בערבוב']],
    ['radio', ['רדיו', 'רדיו המנגן', 'תפעיל רדיו', 'תפעיל את הרדיו']],
    ['radio-song', ['רדיו מהשיר הזה', 'עוד שירים כאלה', 'עוד כאלה', 'שירים דומים']],
    ['what', ['מה מתנגן', 'מה מתנגן עכשיו', 'איזה שיר זה', 'מה השיר הזה', 'מה זה']],
  ];
  const clean = (t) => ` ${String(t || '').replace(/[.,!?״"]/g, ' ').replace(/\s+/g, ' ').trim()} `
    .replace(POLITE, ' ').replace(/\s+/g, ' ').trim();
  const LOOKUP = new Map();
  for (const [name, phrases] of COMMANDS) for (const ph of phrases) LOOKUP.set(clean(ph) || ph, name);

  // People say the same command in many ways: "תעבור לשיר הבא", "אפשר את הבא?",
  // "תדלג על השיר הזה", "תעשה יותר חזק", "תחזור לשיר הקודם". Words around the
  // command are taken off before looking it up; what is left must be a command.
  const LEAD = new Set(['אפשר', 'תוכל', 'תוכלי', 'בוא', 'בואו', 'נו', 'יאללה', 'רגע', 'היי', 'אולי', 'תעשה', 'עשה',
    'תעשי', 'תן', 'תני', 'אני', 'רוצה', 'צריך', 'בבקשה']);
  const VERBS = new Set(['תעבור', 'עבור', 'לעבור', 'תעביר', 'העבר', 'להעביר', 'תלך', 'לך', 'ללכת', 'תדלג', 'דלג',
    'לדלג', 'תשים', 'שים', 'לשים', 'תפעיל', 'הפעל', 'תחזיר', 'החזר', 'תחזור', 'לחזור', 'חזור', 'תקפוץ', 'קפוץ']);
  const TRAIL = new Set(['רגע', 'לרגע', 'הזה', 'הזאת', 'עכשיו', 'כבר', 'על', 'אחד', 'שנייה', 'בבקשה', 'תודה', 'ממנו',
    'הלאה']);
  function reduce(key) {
    let w = key.split(' ').filter(Boolean);
    let changed = true;
    while (changed && w.length > 1) {
      changed = false;
      if (LEAD.has(w[0])) { w = w.slice(1); changed = true; }
      if (w.length > 1 && TRAIL.has(w[w.length - 1])) { w = w.slice(0, -1); changed = true; }
    }
    // "תעביר לשיר הבא", "תדלג על הזה": the verb goes when a command follows it.
    if (w.length > 1 && VERBS.has(w[0]) && LOOKUP.has(w.slice(1).join(' '))) w = w.slice(1);
    return w.join(' ');
  }

  // "תכבה בעוד חצי שעה", "טיימר שינה עשרים דקות", "תכבה בסוף השיר", "בטל את הטיימר".
  const NUMBERS = { 'חמש': 5, 'עשר': 10, 'רבע שעה': 15, 'עשרים': 20, 'חצי שעה': 30, 'ארבעים': 40,
    'ארבעים וחמש': 45, 'שלושת רבעי שעה': 45, 'שעה': 60, 'שעה וחצי': 90, 'שעתיים': 120 };
  V.sleepFor = function sleepFor(text) {
    const t = clean(text);
    if (!/(טיימר|תכבה|כבה|לכבות|תפסיק|להפסיק|לישון|שינה)/.test(t)) return null;
    if (/(בטל|תבטל|לבטל)/.test(t)) return 'off';
    if (/(סוף|אחרי) ה?שיר/.test(String(text)) || /(בסוף|אחרי)$/.test(t)) return 'track';
    const digits = t.match(/(\d+)\s*(דקות|דק|שעות|שעה)?/);
    if (digits) return Number(digits[1]) * (/שע/.test(digits[2] || '') ? 60 : 1);
    const words = Object.keys(NUMBERS).sort((a, b) => b.length - a.length);
    const hit = words.find((w) => t.includes(w));
    return hit ? NUMBERS[hit] : null;
  };

  // Heard without a click (handsfree.js), a word that could be part of a song
  // ("שוב", "נגן", "רדיו", "מה זה") is not taken as a command.
  const LOOSE = new Set(['שוב', 'אחורה', 'נגן', 'תנגן', 'play', 'רדיו', 'מה זה', 'בערבוב', 'כאלה', 'next', 'stop',
    'pause', 'די', 'מספיק', 'שקט', 'חזק', 'חלש', 'הלאה', 'החלף', 'תחזור']);
  V.commandFor = (text, opts = {}) => {
    const key = clean(text);
    if (opts.strict && (LOOSE.has(key) || LOOSE.has(String(text || '').trim()))) return null;
    return LOOKUP.get(key) || LOOKUP.get(String(text || '').trim()) || LOOKUP.get(reduce(key))
      || (V.sleepFor(text) !== null ? 'sleep' : null);
  };

  V.command = function command(text) {
    const name = V.commandFor(text);
    if (!name) return false;
    const P = H.player;
    const cur = P.current();
    const say = (msg, ic) => H.toast(msg, { icon: ic });
    if (name === 'next') { P.next(); say('לשיר הבא', 'skip-forward'); }
    else if (name === 'prev') { P.prev(); say('לשיר הקודם', 'skip-back'); }
    else if (name === 'pause') { P.toggle(false); say('עצרתי', 'pause'); }
    else if (name === 'play') { P.toggle(true); say('ממשיך לנגן', 'play'); }
    else if (name === 'louder') { P.setVolume(Math.min(1, P.volume() + 0.15)); say(`עוצמה ${Math.round(P.volume() * 100)}%`, 'volume-2'); }
    else if (name === 'quieter') { P.setVolume(Math.max(0.05, P.volume() - 0.15)); say(`עוצמה ${Math.round(P.volume() * 100)}%`, 'volume-1'); }
    else if (name === 'shuffle') { P.setShuffle(true); say('בערבוב', 'shuffle'); }
    else if (name === 'radio') H.radioFrom(null);
    else if (name === 'radio-song') {
      if (cur) H.radioFrom(cur);
      else H.radioFrom(null);
    } else if (name === 'sleep') {
      const v = V.sleepFor(text);
      P.setSleep(v);
      say(v === 'off' ? 'טיימר השינה בוטל' : v === 'track' ? 'יכבה בסוף השיר' : `יכבה בעוד ${v} דקות`, 'moon');
    } else if (name === 'what') {
      say(cur ? `מתנגן: ${H.trackTitle(cur)}${cur.artist ? ` · ${cur.artist}` : ''}` : 'כרגע לא מתנגן כלום', 'music-2');
    }
    return true;
  };

  V.toggle = async function toggle() {
    if (V.state === 'listening' && session) { session.stop(); return; }
    if (V.state !== 'idle') return;
    setState('preparing');
    let ready = false;
    try {
      ready = await ensureModel();
    } catch (err) {
      H.toast(err.message, { kind: 'bad' });
    }
    if (!ready) { setState('idle'); return; }
    await listen();
  };

  V.cancel = function cancel() { if (session) session.stop(true); };

  /** The microphone button (the request line puts one beside the input). */
  V.button = function button() {
    const b = h('button', { class: 'mic-btn', type: 'button', 'data-state': 'idle', 'aria-pressed': 'false',
      'aria-label': 'בקשה בקול', title: 'בקשה בקול', onclick: () => V.toggle() }, icon('mic'));
    buttons.add(b);
    return b;
  };

  api.on('voice-level', ({ level }) => {
    for (const b of buttons) b.style.setProperty('--level', level.toFixed(2));
  });
})();
