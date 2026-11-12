'use strict';

/*
 * The player: one <audio> element that plays either a queue of local songs
 * or a live radio stream, plus everything around it — the dock, shuffle and
 * repeat, the sleep timer, play counting, Windows' media overlay (through the
 * Media Session API) and the taskbar buttons.
 */
(function () {
  const api = H.api;
  const audio = H.$('#audio');
  const P = {
    queue: [],        // songs in play order
    original: [],     // the same songs in the order they were given
    index: -1,
    mode: 'idle',     // 'idle' | 'track' | 'radio'
    station: null,
    shuffle: H.storage.get('shuffle', false),
    repeat: H.storage.get('repeat', 'off'), // 'off' | 'all' | 'one'
    sleep: null,      // { endAt } | { endOfTrack: true }
  };
  const listeners = new Set();
  let hls = null;
  let counted = false;
  let errorsInARow = 0;
  let triedHlsFallback = false;
  let fading = false;
  let volume = H.storage.get('volume', 0.9);
  let muted = false;

  P.on = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
  P.current = () => (P.mode === 'track' ? P.queue[P.index] || null : null);
  P.isPlaying = () => P.mode !== 'idle' && !audio.paused;

  function changed(what) {
    for (const fn of listeners) {
      try { fn(what, P); } catch (err) { console.error(err); }
    }
    renderDock();
    updateSession();
    reportState();
  }

  // ------------------------------------------------------------ queue
  function shuffled(list) {
    const a = list.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  /** Play a list from `start`. `{ shuffle: true }` plays it mixed. */
  P.playList = function playList(tracks, start = 0, opts = {}) {
    if (!tracks || !tracks.length) return;
    P.autoRadio = opts.autoRadio || null;
    P.original = tracks.slice();
    P.listCrossfade = Number.isFinite(opts.crossfade) ? opts.crossfade : null;
    if (opts.shuffle !== undefined) setShuffleFlag(!!opts.shuffle);
    if (P.shuffle) {
      const first = opts.shuffle ? tracks[Math.floor(Math.random() * tracks.length)] : tracks[start];
      P.queue = [first, ...shuffled(tracks.filter((t) => t !== first))];
      playIndex(0);
    } else {
      P.queue = tracks.slice();
      playIndex(start);
    }
  };

  P.enqueue = function enqueue(tracks) {
    if (!tracks || !tracks.length) return;
    if (P.mode !== 'track' || !P.queue.length) {
      P.playList(tracks, 0);
      return;
    }
    P.queue.push(...tracks);
    P.original.push(...tracks);
    changed('queue');
  };

  P.playNext = function playNext(track) {
    if (P.mode !== 'track' || !P.queue.length) { P.playList([track], 0); return; }
    P.queue.splice(P.index + 1, 0, track);
    P.original.push(track);
    changed('queue');
  };

  P.removeAt = function removeAt(i) {
    if (i < 0 || i >= P.queue.length) return;
    const [gone] = P.queue.splice(i, 1);
    P.original = P.original.filter((t) => t !== gone);
    if (i < P.index) P.index -= 1;
    else if (i === P.index) {
      if (P.queue.length) playIndex(Math.min(i, P.queue.length - 1));
      else stop();
      return;
    }
    changed('queue');
  };

  P.jump = (i) => playIndex(i);

  function setShuffleFlag(on) {
    P.shuffle = on;
    H.storage.set('shuffle', on);
  }

  P.setShuffle = function setShuffle(on) {
    setShuffleFlag(on);
    const cur = P.current();
    if (P.mode === 'track' && cur) {
      if (on) {
        P.queue = [cur, ...shuffled(P.original.filter((t) => t !== cur))];
        P.index = 0;
      } else {
        P.queue = P.original.slice();
        P.index = Math.max(0, P.queue.indexOf(cur));
      }
    }
    changed('mode');
  };

  P.cycleRepeat = function cycleRepeat() {
    P.repeat = { off: 'all', all: 'one', one: 'off' }[P.repeat] || 'off';
    H.storage.set('repeat', P.repeat);
    changed('mode');
  };

  // ------------------------------------------------------------ playback
  function stopHls() {
    if (hls) {
      try { hls.destroy(); } catch { /* ignore */ }
      hls = null;
    }
  }

  function stop() {
    stopHls();
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    P.mode = 'idle';
    P.station = null;
    P.index = -1;
    changed('stop');
  }
  P.stop = stop;

  // Songs from YouTube played without saving: made ready (a small cache in the
  // core) just before they play, and the next one while this one plays.
  const preparing = new WeakMap();
  let loadToken = 0;
  function prepareListen(track) {
    if (!track || !track.listen || track.path) return Promise.resolve(true);
    if (preparing.has(track)) return preparing.get(track);
    const job = api.listenPrepare(track.result).then((r) => {
      if (r && r.ok) { track.path = r.path; return true; }
      track.failed = (r && r.message) || 'השיר לא זמין כרגע';
      return false;
    }).catch((err) => { track.failed = err.message; return false; })
      .finally(() => preparing.delete(track));
    preparing.set(track, job);
    return job;
  }
  P.prepareListen = prepareListen;

  function playIndex(i, opts = {}) {
    if (i < 0 || i >= P.queue.length) return;
    if (xfade && !opts.keepFade) endCrossfade();
    const track = P.queue[i];
    if (track.listen && !track.path) {
      const token = ++loadToken;
      stopHls();
      audio.pause();
      P.mode = 'track';
      P.station = null;
      P.index = i;
      P.loading = true;
      changed('track');
      prepareListen(track).then((ok) => {
        if (token !== loadToken) return;   // the listener moved on meanwhile
        P.loading = false;
        if (ok) { playIndex(i); return; }
        H.toast(`„${H.trackTitle(track)}” לא הושמע: ${track.failed}`, { kind: 'bad' });
        if (i + 1 < P.queue.length) playIndex(i + 1);
        else changed('end');
      });
      return;
    }
    loadToken += 1;
    P.loading = false;
    stopHls();
    P.mode = 'track';
    P.station = null;
    P.index = i;
    counted = false;
    // Skip the silence before the music (media fragment: start at that second).
    const lead = P.skipSilence && track.lead >= 0.6 ? track.lead : 0;
    audio.src = api.fileUrl(track.path) + (lead ? `#t=${lead.toFixed(2)}` : '');
    applyVolume();
    audio.play().catch(() => { /* reported by the error event */ });
    changed('track');
    topUpRadio();
    const next = P.queue[i + 1];
    if (next && next.listen && !next.path) setTimeout(() => prepareListen(next), 1500);
  }

  P.next = function next(auto = false) {
    if (P.mode !== 'track') return;
    if (auto && P.repeat === 'one') {
      audio.currentTime = 0;
      audio.play().catch(() => {});
      counted = false;
      return;
    }
    if (P.index + 1 < P.queue.length) playIndex(P.index + 1);
    else if (P.repeat === 'all' && P.queue.length) playIndex(0);
    else if (auto) {
      audio.pause();
      changed('end');
    }
  };

  P.prev = function prev() {
    if (P.mode !== 'track') return;
    if (audio.currentTime > 3 || P.index === 0) {
      audio.currentTime = 0;
      return;
    }
    playIndex(P.index - 1);
  };

  P.toggle = function toggle(force) {
    if (P.mode === 'idle') {
      if (P.queue.length) playIndex(Math.max(0, P.index));
      return;
    }
    const play = force === undefined ? audio.paused : force;
    if (play) audio.play().catch(() => {});
    else audio.pause();
  };

  P.seekTo = (sec) => {
    if (P.mode === 'track' && Number.isFinite(audio.duration)) audio.currentTime = Math.max(0, Math.min(sec, audio.duration));
  };

  // ------------------------------------------------------------ רדיו המנגן
  // A station from the listener's own songs (core: station): when two songs
  // are left, the next ones are asked for and added, so it plays on.
  P.autoRadio = null;   // { seed, title, history: [ids], loading }
  P.playRadio = function playRadio(res) {
    if (!res || !res.tracks || !res.tracks.length) return false;
    P.playList(res.tracks, 0, { shuffle: false, autoRadio: { seed: res.seed || null, title: res.title,
      history: res.tracks.map((t) => t.id), loading: false } });
    return true;
  };
  function topUpRadio() {
    const r = P.autoRadio;
    if (!r || r.loading || P.queue.length - P.index > 2) return;
    r.loading = true;
    api.station(r.seed, r.history, 8).then((res) => {
      if (P.autoRadio !== r || !res || !res.tracks) return;
      const fresh = res.tracks.filter((t) => !r.history.includes(t.id));
      r.history.push(...fresh.map((t) => t.id));
      P.queue.push(...fresh);
      P.original.push(...fresh);
      changed('queue');
    }).catch(() => {}).finally(() => { r.loading = false; });
  }

  // ------------------------------------------------------------ radio
  const isHlsUrl = (url) => /\.m3u8(\?|$)/i.test(url);

  function attachHls(url) {
    if (!(window.Hls && window.Hls.isSupported())) return false;
    stopHls();
    hls = new window.Hls({ enableWorker: true, lowLatencyMode: false });
    hls.loadSource(url);
    hls.attachMedia(audio);
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => audio.play().catch(() => {}));
    hls.on(window.Hls.Events.ERROR, (_e, data) => {
      if (!data || !data.fatal) return;
      if (data.type === window.Hls.ErrorTypes.NETWORK_ERROR && hls) {
        hls.startLoad();
        return;
      }
      if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR && hls) {
        hls.recoverMediaError();
        return;
      }
      H.toast(`השידור של "${P.station ? P.station.title : ''}" לא זמין כרגע`, { kind: 'bad' });
      stop();
    });
    return true;
  }

  P.playStation = function playStation(station) {
    stopHls();
    P.mode = 'radio';
    P.station = station;
    triedHlsFallback = false;
    applyVolume();
    if (isHlsUrl(station.url) && attachHls(station.url)) {
      triedHlsFallback = true;
    } else {
      audio.src = station.url;
      audio.play().catch(() => {});
    }
    changed('station');
  };

  // ------------------------------------------------------------ volume
  // Even loudness: a loud song plays a little quieter (gain from the core,
  // never above 1, so nothing distorts).
  P.normalize = true;
  P.skipSilence = true;
  P.setSoundOptions = function setSoundOptions({ normalize, skipSilence } = {}) {
    if (normalize !== undefined) P.normalize = !!normalize;
    if (skipSilence !== undefined) P.skipSilence = !!skipSilence;
    applyVolume();
  };
  // While the microphone listens, the music steps back (P.duck).
  let ducked = false;
  P.duck = function duck(on) { ducked = !!on; applyVolume(); };
  function songFactor() {
    const d = ducked ? 0.12 : 1;
    const cur = P.mode === 'track' ? P.queue[P.index] : null;
    if (!P.normalize || !cur || !cur.gain) return d;
    return d * Math.min(1, Math.pow(10, cur.gain / 20));
  }
  P.songFactor = songFactor;
  function applyVolume() {
    if (!fading) audio.volume = muted ? 0 : volume * songFactor();
  }
  P.setVolume = function setVolume(v) {
    volume = Math.max(0, Math.min(1, v));
    muted = volume === 0 ? muted : false;
    H.storage.set('volume', volume);
    applyVolume();
    renderVolume();
  };
  P.toggleMute = function toggleMute() {
    muted = !muted;
    applyVolume();
    renderVolume();
  };
  P.volume = () => (muted ? 0 : volume);

  // ------------------------------------------------------------ sleep timer
  P.setSleep = function setSleep(value) {
    if (value === 'off' || value === null) P.sleep = null;
    else if (value === 'track') P.sleep = { endOfTrack: true };
    else P.sleep = { endAt: Date.now() + Number(value) * 60000, minutes: Number(value) };
    if (fading) { fading = false; applyVolume(); }
    renderSleep();
    changed('sleep');
  };

  function sleepTick() {
    if (!P.sleep || !P.sleep.endAt) return;
    const left = (P.sleep.endAt - Date.now()) / 1000;
    if (left <= 0) {
      audio.pause();
      fading = false;
      P.sleep = null;
      applyVolume();
      renderSleep();
      H.toast('טיימר השינה עצר את הנגינה. לילה טוב', { icon: 'moon' });
      changed('sleep');
      return;
    }
    if (left <= 10 && P.isPlaying()) {
      fading = true;
      audio.volume = (muted ? 0 : volume * songFactor()) * (left / 10);
    }
    renderSleep();
  }
  setInterval(sleepTick, 1000);

  // ------------------------------------------------------------ soft transitions
  // At the end of a song the next one starts quietly and rises while the
  // leaving one, handed to a second element, fades away. The main element
  // simply moves on to the next song, so everything else works as usual.
  const ghost = new Audio();
  ghost.preload = 'auto';
  let xfade = null;          // { t0, ms, from, timer }
  P.crossfade = Number(H.storage.get('crossfade', 0)) || 0;
  P.listCrossfade = null;
  P.setCrossfade = (seconds) => { P.crossfade = Number(seconds) || 0; H.storage.set('crossfade', P.crossfade); };
  const fadeSeconds = () => (P.listCrossfade != null ? Math.max(P.listCrossfade, P.crossfade) : P.crossfade);

  function endCrossfade() {
    if (!xfade) return;
    clearInterval(xfade.timer);
    xfade = null;
    ghost.pause();
    ghost.removeAttribute('src');
    ghost.load();
    fading = false;
    applyVolume();
  }

  function startCrossfade(nextIndex, seconds) {
    const nextTrack = P.queue[nextIndex];
    if (!nextTrack || (nextTrack.listen && !nextTrack.path)) return false;
    ghost.src = audio.src;
    ghost.currentTime = audio.currentTime;
    ghost.volume = audio.volume;
    ghost.play().catch(() => {});
    const from = audio.volume;
    fading = true;
    xfade = { t0: Date.now(), ms: seconds * 1000, from, timer: null };
    playIndex(nextIndex, { keepFade: true });
    audio.volume = 0;
    xfade.timer = setInterval(() => {
      if (!xfade) return;
      const k = Math.min(1, (Date.now() - xfade.t0) / xfade.ms);
      ghost.volume = Math.max(0, xfade.from * (1 - k) * (1 - k));
      audio.volume = (muted ? 0 : volume * songFactor()) * Math.sqrt(k);
      if (k >= 1) endCrossfade();
    }, 50);
    return true;
  }

  // Where the music really ends: before the silence at the end of the file.
  function musicEnd() {
    const cur = P.current();
    const tail = P.skipSilence && cur && cur.tail >= 1.5 ? cur.tail : 0;
    return audio.duration - tail;
  }

  function maybeCrossfade() {
    const seconds = fadeSeconds();
    if (!seconds || xfade || P.mode !== 'track' || audio.paused || P.repeat === 'one' || P.blocked) return;
    if (P.sleep && P.sleep.endOfTrack) return;
    if (!Number.isFinite(audio.duration) || audio.duration < seconds * 3) return;
    const left = musicEnd() - audio.currentTime;
    if (left > seconds) return;
    const nextIndex = P.index + 1 < P.queue.length ? P.index + 1 : (P.repeat === 'all' && P.queue.length > 1 ? 0 : -1);
    if (nextIndex >= 0) startCrossfade(nextIndex, Math.max(1, left));
  }

  // ------------------------------------------------------------ Shabbat mode
  // While Shabbat mode holds the player nothing plays — not a click, a media
  // key or a download that finished. Before that the music fades to silence.
  let restFade = null;
  P.blocked = false;
  P.setBlocked = function setBlocked(on) {
    P.blocked = !!on;
    if (P.blocked) {
      endCrossfade();
      audio.pause();
      if (P.sleep) { P.sleep = null; renderSleep(); }
    }
    changed('blocked');
  };
  P.fadeOutAndStop = function fadeOutAndStop(ms) {
    if (restFade) return Promise.resolve();
    endCrossfade();
    if (!P.isPlaying()) { audio.pause(); return Promise.resolve(); }
    return new Promise((resolve) => {
      const from = audio.volume;
      const t0 = Date.now();
      fading = true;
      restFade = setInterval(() => {
        const k = Math.min(1, (Date.now() - t0) / Math.max(ms, 1));
        audio.volume = from * (1 - k) * (1 - k);
        if (k >= 1) {
          clearInterval(restFade);
          restFade = null;
          audio.pause();
          fading = false;
          applyVolume();
          resolve();
        }
      }, 200);
    });
  };

  // ------------------------------------------------------------ audio events
  audio.addEventListener('play', () => {
    if (P.blocked) { audio.pause(); return; }
    changed('play');
  });
  audio.addEventListener('pause', () => { if (xfade) endCrossfade(); changed('pause'); });
  audio.addEventListener('playing', () => { errorsInARow = 0; });
  audio.addEventListener('ended', () => {
    if (P.sleep && P.sleep.endOfTrack) {
      P.sleep = null;
      renderSleep();
      H.toast('השיר הסתיים והנגינה נעצרה, כמו שביקשת', { icon: 'moon' });
      changed('end');
      return;
    }
    P.next(true);
  });
  audio.addEventListener('timeupdate', () => {
    renderProgress();
    maybeCrossfade();
    // No crossfade: once the music has ended, the silence after it is skipped.
    if (!xfade && P.mode === 'track' && !audio.paused && Number.isFinite(audio.duration)
        && musicEnd() < audio.duration && audio.currentTime >= musicEnd()) {
      audio.dispatchEvent(new Event('ended'));
      return;
    }
    const cur = P.current();
    if (cur && !cur.listen && !counted && audio.currentTime >= Math.min(30, (audio.duration || 60) * 0.5)) {
      counted = true;
      api.recordPlay(cur.id).then(() => api.emit('played', cur)).catch(() => {});
    }
  });
  audio.addEventListener('durationchange', renderProgress);
  audio.addEventListener('error', () => {
    if (P.mode === 'radio') {
      // Some channels are HLS without a .m3u8 address: try that once.
      if (!triedHlsFallback && P.station && attachHls(P.station.url)) {
        triedHlsFallback = true;
        return;
      }
      if (P.station) H.toast(`השידור של "${P.station.title}" לא זמין כרגע`, { kind: 'bad' });
      stop();
      return;
    }
    const cur = P.current();
    if (!cur) return;
    errorsInARow += 1;
    H.toast(`לא הצלחתי לנגן את "${H.trackTitle(cur)}" — אולי הקובץ הוזז או נמחק`, { kind: 'bad' });
    if (errorsInARow >= 3) {
      errorsInARow = 0;
      audio.pause();
      changed('error');
      return;
    }
    setTimeout(() => P.next(true), 1200);
  });

  // ------------------------------------------------------------ the dock
  const dock = H.$('#dock');
  const seek = H.$('#seek');
  const volumeInput = H.$('#volume');
  let seeking = false;

  function renderDock() {
    const cur = P.current();
    const coverHost = H.$('#dock-cover');
    H.clear(coverHost);
    coverHost.className = 'cover cover-sm';
    const heart = H.$('#dock-heart');
    if (P.mode === 'radio' && P.station) {
      H.$('#dock-title').textContent = P.station.title;
      H.$('#dock-sub').textContent = P.station.now_playing || 'קול חי · שידור חי';
      coverHost.classList.add('cover-radio');
      coverHost.textContent = H.letter(P.station.title);
      heart.disabled = true;
      heart.setAttribute('aria-pressed', 'false');
    } else if (cur && cur.listen) {
      H.$('#dock-title').textContent = H.trackTitle(cur);
      H.$('#dock-sub').textContent = P.loading ? 'מכין את השיר מיוטיוב…' : [cur.artist, 'מיוטיוב, בלי לשמור'].filter(Boolean).join(' · ');
      coverHost.textContent = H.letter(H.trackTitle(cur));
      heart.disabled = true;
      heart.setAttribute('aria-pressed', 'false');
    } else if (cur) {
      H.$('#dock-title').textContent = H.trackTitle(cur);
      H.$('#dock-sub').textContent = [cur.artist, cur.album].filter(Boolean).join(' · ') || cur.filename || '';
      coverHost.dataset.tint = H.tint(cur.topic);
      coverHost.textContent = H.letter(H.trackTitle(cur));
      heart.disabled = false;
      heart.setAttribute('aria-pressed', cur.favorite ? 'true' : 'false');
      heart.dataset.favId = cur.id;
    } else {
      H.$('#dock-title').textContent = 'שום דבר לא מתנגן';
      H.$('#dock-sub').textContent = 'בחרו שיר, נושא או ערוץ';
      coverHost.dataset.tint = 'none';
      coverHost.textContent = '♪';
      heart.disabled = true;
    }
    const playing = P.isPlaying();
    dock.classList.toggle('playing', playing);
    const playBtn = H.$('#btn-play');
    H.setIcon(playBtn, playing ? 'pause' : 'play');
    playBtn.setAttribute('aria-label', playing ? 'השהה' : 'נגן');
    const radio = P.mode === 'radio';
    H.$('#progress').hidden = radio;
    H.$('#live-line').hidden = !radio;
    H.$('#btn-prev').disabled = radio || P.mode === 'idle';
    H.$('#btn-next').disabled = radio || P.mode === 'idle';
    H.$('#btn-shuffle').disabled = radio;
    H.$('#btn-repeat').disabled = radio;
    H.$('#btn-shuffle').setAttribute('aria-pressed', P.shuffle ? 'true' : 'false');
    const rep = H.$('#btn-repeat');
    rep.setAttribute('aria-pressed', P.repeat !== 'off' ? 'true' : 'false');
    rep.setAttribute('aria-label', { off: 'חזרה: כבויה', all: 'חזרה על כל הרשימה', one: 'חזרה על השיר הזה' }[P.repeat]);
    H.setIcon(rep, P.repeat === 'one' ? 'repeat-1' : 'repeat');
    H.$('#nav-live').hidden = !(radio && playing);
    document.title = P.mode === 'idle' ? 'המנגן' : `${radio ? P.station.title : H.trackTitle(cur)} · המנגן`;
    renderProgress();
  }

  function renderProgress() {
    if (P.mode !== 'track') return;
    const dur = audio.duration;
    const cur = audio.currentTime;
    H.$('#time-cur').textContent = H.clock(cur);
    H.$('#time-dur').textContent = Number.isFinite(dur) ? H.clock(dur) : H.clock((P.current() || {}).duration || 0);
    if (!seeking) {
      seek.value = Number.isFinite(dur) && dur > 0 ? String(Math.round((cur / dur) * 1000)) : '0';
      H.fillRange(seek);
    }
  }

  function renderVolume() {
    const v = P.volume();
    volumeInput.value = String(Math.round(v * 100));
    H.fillRange(volumeInput);
    H.setIcon(H.$('#btn-mute'), v === 0 ? 'volume-x' : v < 0.5 ? 'volume-1' : 'volume-2');
  }

  function renderSleep() {
    const label = H.$('#sleep-label');
    const btn = H.$('#btn-sleep');
    if (!P.sleep) {
      label.textContent = '';
      btn.setAttribute('aria-pressed', 'false');
    } else if (P.sleep.endOfTrack) {
      label.textContent = 'סוף השיר';
      btn.setAttribute('aria-pressed', 'true');
    } else {
      const left = Math.max(0, Math.round((P.sleep.endAt - Date.now()) / 1000));
      label.textContent = H.clock(left);
      btn.setAttribute('aria-pressed', 'true');
    }
  }

  seek.addEventListener('input', () => { seeking = true; H.fillRange(seek); });
  seek.addEventListener('change', () => {
    seeking = false;
    if (Number.isFinite(audio.duration)) audio.currentTime = (Number(seek.value) / 1000) * audio.duration;
  });
  volumeInput.addEventListener('input', () => P.setVolume(Number(volumeInput.value) / 100));
  H.$('#btn-mute').addEventListener('click', () => P.toggleMute());
  H.$('#btn-play').addEventListener('click', () => P.toggle());
  H.$('#btn-next').addEventListener('click', () => P.next());
  H.$('#btn-prev').addEventListener('click', () => P.prev());
  H.$('#btn-shuffle').addEventListener('click', () => P.setShuffle(!P.shuffle));
  H.$('#btn-repeat').addEventListener('click', () => P.cycleRepeat());
  H.$('#dock-heart').addEventListener('click', () => {
    const cur = P.current();
    if (cur) H.toggleFavorite(cur);
  });

  // Taskbar buttons and media keys arrive as commands.
  api.on('player-command', (cmd) => {
    if (cmd === 'toggle') P.toggle();
    else if (cmd === 'next') P.next();
    else if (cmd === 'previous') P.prev();
  });

  // ------------------------------------------------------------ Windows media overlay
  const session = 'mediaSession' in navigator ? navigator.mediaSession : null;
  const artCache = new Map();

  /** Draw the song's letter cover as artwork for the system media overlay. */
  function artwork(letter, tint) {
    const key = `${letter}|${tint}`;
    if (artCache.has(key)) return artCache.get(key);
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 256;
    const ctx = canvas.getContext('2d');
    const css = getComputedStyle(document.documentElement);
    ctx.fillStyle = css.getPropertyValue('--mantle').trim() || '#16365F';
    ctx.fillRect(0, 0, 256, 256);
    ctx.fillStyle = css.getPropertyValue('--thread').trim() || '#D8B25E';
    ctx.fillRect(0, 226, 256, 4);
    ctx.fillRect(0, 234, 256, 2);
    ctx.font = `500 150px ${css.getPropertyValue('--font-display')}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(letter, 128, 112);
    const url = canvas.toDataURL('image/png');
    artCache.set(key, url);
    return url;
  }

  function updateSession() {
    if (!session) return;
    const cur = P.current();
    if (P.mode === 'idle') {
      session.metadata = null;
      session.playbackState = 'none';
      return;
    }
    const title = P.mode === 'radio' ? P.station.title : H.trackTitle(cur);
    const artist = P.mode === 'radio' ? (P.station.now_playing || 'קול חי') : (cur.artist || '');
    try {
      session.metadata = new window.MediaMetadata({
        title,
        artist,
        album: P.mode === 'radio' ? 'רדיו · קול חי' : (cur.album || 'המנגן'),
        artwork: [{ src: artwork(H.letter(title), P.mode === 'radio' ? 'radio' : H.tint(cur.topic)), sizes: '256x256', type: 'image/png' }],
      });
    } catch { /* not supported */ }
    session.playbackState = P.isPlaying() ? 'playing' : 'paused';
  }

  if (session) {
    const handle = (action, fn) => { try { session.setActionHandler(action, fn); } catch { /* unsupported */ } };
    handle('play', () => P.toggle(true));
    handle('pause', () => P.toggle(false));
    handle('previoustrack', () => P.prev());
    handle('nexttrack', () => P.next());
    handle('seekto', (d) => P.seekTo(d.seekTime));
  }

  function reportState() {
    try { api.playerState({ playing: P.isPlaying(), hasTrack: P.mode !== 'idle' }); } catch { /* ignore */ }
  }

  P.audio = audio;
  H.player = P;
  renderVolume();
  renderDock();
  audio.volume = volume;
})();
