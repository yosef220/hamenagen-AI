"""Where the chorus starts (1.5.3), for a ringtone.

A chorus is the part of a song that comes back: the same melody and chords,
two, three or four times, usually a little louder than the verses. So the
song is read once at a low rate, each half second becomes a chroma vector
(how much of each of the twelve notes sounds), and every stretch of the
ringtone's length is compared with every other stretch of the song, along
the diagonals of the self-similarity matrix. The stretch that repeats best
(and is loud) is the chorus; of its returns, the first one that is nearly as
good is taken, so the ringtone starts where the listener first meets it.

Nothing here needs a model: numpy, and soundfile or the bundled ffmpeg to
read the song. When the song has no clear repetition, the answer is None and
the caller falls back to a plain suggestion.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RATE = 11025
HOP_S = 0.5
WIN = 4096


def _read(path, ffmpeg: str | None, np):
    """Mono samples at RATE: soundfile when it can read the file, else ffmpeg."""
    try:
        import soundfile as sf

        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        x = data.mean(axis=1)
        if sr != RATE:
            n = int(len(x) * RATE / sr)
            x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
        return x
    except Exception:  # noqa: BLE001 - try ffmpeg
        pass
    if not ffmpeg:
        return None
    flags = 0x08000000 if sys.platform == "win32" else 0
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                              "-ar", str(RATE), "-f", "f32le", "-"], capture_output=True, timeout=120, check=True,
                             creationflags=flags).stdout
    except Exception:  # noqa: BLE001
        return None
    return np.frombuffer(out, dtype=np.float32)


def features(x, np):
    """(chroma per frame [N, 12], loudness per frame [N]) every HOP_S seconds."""
    hop = int(HOP_S * RATE)
    n = max(0, (len(x) - WIN) // hop + 1)
    if n < 8:
        return None, None
    window = np.hanning(WIN).astype(np.float32)
    freqs = np.fft.rfftfreq(WIN, 1 / RATE)
    band = (freqs >= 80) & (freqs <= 2000)
    pitch = np.round(12 * np.log2(freqs[band] / 440.0) + 69).astype(int) % 12
    chroma = np.zeros((n, 12), dtype=np.float32)
    loud = np.zeros(n, dtype=np.float32)
    for i in range(n):
        frame = x[i * hop: i * hop + WIN]
        loud[i] = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
        mag = np.abs(np.fft.rfft(frame * window))[band]
        chroma[i] = np.bincount(pitch, weights=mag, minlength=12)
    chroma /= np.linalg.norm(chroma, axis=1, keepdims=True) + 1e-9
    return chroma, loud


def best_start(chroma, loud, length_s: float, np, *, skip_s: float = 8.0) -> float | None:
    """The start (seconds) of the stretch of ``length_s`` that repeats best."""
    n = len(chroma)
    L = max(4, int(round(length_s / HOP_S)))
    if n < 2 * L + 4:
        return None
    # Remove what every frame shares (a drone, a held key) so repetition stands out.
    c = chroma - chroma.mean(axis=0, keepdims=True)
    c /= np.linalg.norm(c, axis=1, keepdims=True) + 1e-9
    S = c @ c.T
    rep = np.full(n - L + 1, -1.0, dtype=np.float32)
    kernel = np.ones(L, dtype=np.float32) / L
    for lag in range(L, n - L + 1):
        diag = np.diagonal(S, offset=lag)                     # S[i, i + lag]
        avg = np.convolve(diag, kernel, mode="valid")         # stretch at i vs stretch at i + lag
        k = len(avg)
        np.maximum(rep[:k], avg, out=rep[:k])                 # the earlier stretch repeats later
        np.maximum(rep[lag:lag + k], avg, out=rep[lag:lag + k])   # …and the later one earlier
    if rep.max() < 0.35:
        return None                                           # nothing comes back clearly
    lvl = np.convolve(loud, kernel, mode="valid")[: len(rep)]
    lvl = (lvl - lvl.min()) / (lvl.max() - lvl.min() + 1e-9)
    score = 0.75 * rep + 0.25 * lvl
    skip = int(skip_s / HOP_S)
    score[:skip] = -1
    best = float(score.max())
    if best <= 0:
        return None
    # The first stretch nearly as good as the best: where the chorus first comes.
    first = int(np.argmax(score >= best - 0.04))
    return round(first * HOP_S, 1)


def find_chorus(path, length_s: float = 30, ffmpeg: str | None = None) -> float | None:
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return None
    p = Path(path)
    if not p.is_file():
        return None
    x = _read(p, ffmpeg, np)
    if x is None or len(x) < RATE * 20:
        return None
    x = x[: RATE * 600]                                       # the first ten minutes are enough
    chroma, loud = features(x, np)
    if chroma is None:
        return None
    return best_start(chroma, loud, min(length_s, 20.0), np)
