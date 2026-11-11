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
    P.original = tracks.slice();
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

  function playIndex(i) {
    if (i < 0 || i >= P.queue.length) return;
    stopHls();
    P.mode = 'track';
    P.station = null;
    P.index = i;
    counted = false;
    const track = P.queue[i];
    audio.src = api.fileUrl(track.path);
    applyVolume();
    audio.play().catch(() => { /* reported by the error event */ });
    changed('track');
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
  function applyVolume() {
    if (!fading) audio.volume = muted ? 0 : volume;
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
      audio.volume = (muted ? 0 : volume) * (left / 10);
    }
    renderSleep();
  }
  setInterval(sleepTick, 1000);

  // ------------------------------------------------------------ audio events
  audio.addEventListener('play', () => changed('play'));
  audio.addEventListener('pause', () => changed('pause'));
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
    const cur = P.current();
    if (cur && !counted && audio.currentTime >= Math.min(30, (audio.duration || 60) * 0.5)) {
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
