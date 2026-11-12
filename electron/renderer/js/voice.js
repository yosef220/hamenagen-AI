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
    if (st.available) return true;
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

  async function toPcm(blob) {
    const ctx = new AudioContext({ sampleRate: RATE });
    try {
      const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
      const mono = new Float32Array(audio.length);
      for (let c = 0; c < audio.numberOfChannels; c += 1) {
        const ch = audio.getChannelData(c);
        for (let i = 0; i < ch.length; i += 1) mono[i] += ch[i] / audio.numberOfChannels;
      }
      const pcm = new Int16Array(mono.length);
      for (let i = 0; i < mono.length; i += 1) pcm[i] = Math.max(-1, Math.min(1, mono[i])) * 32767;
      return { pcm, rate: audio.sampleRate };
    } finally {
      ctx.close().catch(() => {});
    }
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
    const meterCtx = new AudioContext();
    const analyser = meterCtx.createAnalyser();
    analyser.fftSize = 1024;
    meterCtx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };

    const started = performance.now();
    let floor = null;
    let heard = false;
    let lastLoud = started;
    let cancelled = false;
    const finished = new Promise((resolve) => { recorder.onstop = resolve; });

    const stop = (cancel = false) => {
      cancelled = cancelled || cancel;
      clearInterval(timer);
      if (recorder.state !== 'inactive') recorder.stop();
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

    H.player.duck(true);
    recorder.start(250);
    setState('listening');
    await finished;
    session = null;
    H.player.duck(false);
    for (const t of stream.getTracks()) t.stop();
    meterCtx.close().catch(() => {});

    if (cancelled || !heard) {
      setState('idle');
      if (!heard) H.toast('לא שמעתי כלום. אפשר ללחוץ שוב ולדבר קרוב יותר למיקרופון.', { icon: 'mic-off' });
      return;
    }
    setState('thinking');
    try {
      const { pcm, rate } = await toPcm(new Blob(chunks, { type: recorder.mimeType }));
      const res = await api.voiceRecognize(toBase64(pcm), rate);
      setState('idle');
      if (!res.ok) {
        H.toast(res.message || 'הזיהוי לא הצליח', { kind: 'bad' });
        return;
      }
      if (!res.request) {
        H.toast('לא הצלחתי להבין את הבקשה. אפשר לנסות שוב.', { icon: 'mic-off' });
        return;
      }
      if (V.command(res.request)) return;
      api.emit('voice-heard', { text: res.request });
      H.ask(res.request);
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
    ['next', ['הבא', 'שיר הבא', 'לשיר הבא', 'תעביר', 'תעביר הלאה', 'הלאה', 'דלג', 'תדלג', 'next']],
    ['prev', ['הקודם', 'שיר קודם', 'לשיר הקודם', 'תחזור', 'אחורה', 'שוב']],
    ['pause', ['עצור', 'תעצור', 'הפסק', 'תפסיק', 'השהה', 'stop', 'pause']],
    ['play', ['המשך', 'תמשיך', 'נגן', 'תנגן', 'play']],
    ['louder', ['תגביר', 'הגבר', 'יותר חזק', 'חזק יותר', 'תגביר את הווליום']],
    ['quieter', ['תנמיך', 'הנמך', 'יותר חלש', 'חלש יותר', 'יותר בשקט', 'תנמיך את הווליום']],
    ['shuffle', ['ערבב', 'תערבב', 'בערבוב']],
    ['radio', ['רדיו', 'רדיו המנגן', 'תפעיל רדיו', 'תפעיל את הרדיו']],
    ['radio-song', ['רדיו מהשיר הזה', 'עוד שירים כאלה', 'עוד כאלה', 'שירים דומים']],
    ['what', ['מה מתנגן', 'מה מתנגן עכשיו', 'איזה שיר זה', 'מה השיר הזה', 'מה זה']],
  ];
  const clean = (t) => ` ${String(t || '').replace(/[.,!?״"]/g, ' ').replace(/\s+/g, ' ').trim()} `
    .replace(POLITE, ' ').replace(/\s+/g, ' ').trim();
  const LOOKUP = new Map();
  for (const [name, phrases] of COMMANDS) for (const ph of phrases) LOOKUP.set(clean(ph) || ph, name);

  V.commandFor = (text) => LOOKUP.get(clean(text)) || LOOKUP.get(String(text || '').trim()) || null;

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
