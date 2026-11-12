"""Tempo and energy of a song, for the "סט לשמחה".

The vocal detector already reads three ten-second windows of every song
(mono, 16 kHz); this module looks at the same windows for how fast the beat
is and how much is going on, so a set can warm up, build to a peak and ease
off, with neighbouring songs close in tempo.

* **tempo** — beats per minute, from the autocorrelation of an onset
  envelope (spectral flux), where the beat must line up at one, two, three
  and four beats; between half and double time, the one nearer 120 wins.
* **pulse** — how clear that beat is (0–1).
* **loudness** — RMS level in dBFS.
* **energy** — one number (0–1) from loudness, onset density, pulse and
  brightness: high for a fast, full, bright dance song; low for a quiet
  ballad or a slow niggun.

Pure numpy; no extra model. The numbers are rough, and meant for ordering
songs, not for a DJ's beat-matching.
"""

from __future__ import annotations

import math

SAMPLE_RATE = 16000
N_FFT = 1024
HOP = 256
MIN_BPM, MAX_BPM = 70.0, 180.0


def _frames(np, x, n: int, hop: int):
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    count = 1 + (len(x) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(count)[:, None]
    return x[idx]


def _onset_envelope(np, x):
    """Spectral flux of the log magnitude: how much new sound starts in
    each 16 ms frame."""
    frames = _frames(np, x.astype(np.float32), N_FFT, HOP) * np.hanning(N_FFT).astype(np.float32)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    logmag = np.log1p(10.0 * mag)
    flux = np.maximum(0.0, np.diff(logmag, axis=0)).sum(axis=1)
    # Remove the slow trend so that only the attacks remain.
    width = max(1, int(0.5 * SAMPLE_RATE / HOP))
    trend = np.convolve(flux, np.ones(width) / width, mode="same")
    env = np.maximum(0.0, flux - trend)
    return env, mag


def _autocorrelation(np, env):
    """Normalised autocorrelation of the onset envelope (``None`` if flat)."""
    env = env - env.mean()
    if not np.any(env):
        return None
    n = len(env)
    spec = np.fft.rfft(env, 2 * n)
    acf = np.fft.irfft(spec * np.conj(spec))[:n]
    return acf / (acf[0] + 1e-9)


# Candidate tempos, and how many multiples of a beat must line up: a true beat
# repeats at 1, 2, 3 and 4 beats, while a beat-and-a-half (a kick landing on
# the off-beat hi-hat) only lines up at every other multiple.
_BPM_GRID_STEP = 0.5
_MULTIPLES = (1, 2, 3, 4)


def _tempo_scores(np, acf):
    frame_s = HOP / SAMPLE_RATE
    bpm = np.arange(MIN_BPM, MAX_BPM + _BPM_GRID_STEP, _BPM_GRID_STEP)
    lag = 60.0 / (bpm * frame_s)
    positions = np.arange(len(acf))
    comb = np.zeros_like(bpm)
    for k in _MULTIPLES:
        comb += np.interp(k * lag, positions, acf, right=0.0)
    return bpm, comb / len(_MULTIPLES)


def analyze_windows(windows: list, sr: int = SAMPLE_RATE) -> dict | None:
    """Tempo, pulse, loudness and energy from a song's windows (``None``
    when there is nothing to hear)."""
    try:
        import numpy as np
    except ImportError:
        return None
    if sr != SAMPLE_RATE or not windows:
        return None
    total_curve = None
    bpm_grid = None
    rms_db, densities, centroids, pulses = [], [], [], []
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SAMPLE_RATE)
    for x in windows:
        x = np.asarray(x, dtype=np.float32)
        rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
        if rms < 1e-4:   # silence (or padding)
            continue
        rms_db.append(20 * math.log10(rms))
        env, mag = _onset_envelope(np, x)
        power = mag.sum(axis=1)
        loud = power > power.mean() * 0.1
        if np.any(loud):
            centroids.append(float((mag[loud] * freqs).sum() / (mag[loud].sum() + 1e-9)))
        # Onsets: local peaks of the envelope above its typical level.
        if len(env) > 3:
            thr = env.mean() + env.std()
            peaks = (env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > thr)
            densities.append(float(peaks.sum()) / (len(x) / SAMPLE_RATE))
        acf = _autocorrelation(np, env)
        if acf is not None and len(acf) > 4 * 60.0 / (MIN_BPM * HOP / SAMPLE_RATE):
            bpm_grid, curve = _tempo_scores(np, acf)
            pulses.append(float(max(0.0, curve.max())))
            total_curve = curve if total_curve is None else total_curve + curve
    if not rms_db:
        return None
    tempo = None
    if total_curve is not None and np.any(total_curve > 0):
        # Of half and double time, prefer the one nearer 120 BPM, as people tap.
        weight = np.exp(-0.5 * (np.log2(bpm_grid / 120.0) / 1.0) ** 2)
        score = total_curve * (0.6 + 0.4 * weight)
        i = int(np.argmax(score))
        tempo = float(bpm_grid[i])
    loudness = float(sum(rms_db) / len(rms_db))
    density = float(sum(densities) / len(densities)) if densities else 0.0
    brightness = float(sum(centroids) / len(centroids)) if centroids else 0.0
    pulse = float(sum(pulses) / len(pulses)) if pulses else 0.0

    def unit(v, lo, hi):
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    energy = (0.35 * unit(loudness, -30.0, -9.0) + 0.25 * unit(density, 0.5, 5.0)
              + 0.2 * unit(pulse, 0.05, 0.5) + 0.2 * unit(brightness, 600.0, 3200.0))
    return {
        "tempo": round(tempo, 1) if tempo else None,
        "pulse": round(pulse, 3),
        "loudness": round(loudness, 1),
        "energy": round(energy, 3),
    }


def tempo_distance(a: float | None, b: float | None) -> float:
    """How far two tempos are, counting half and double time as near."""
    if not a or not b:
        return 30.0
    return min(abs(a - b), abs(a - 2 * b), abs(2 * a - b))
