"""Recognising a cappella songs by listening.

In the Omer count and the Three Weeks many listeners hear only vocal music —
singing with no instruments. Song titles say "ווקאלי" only sometimes, so this
module listens: three windows of ten seconds, at 20%, 50% and 80% of the song
(intros and endings often differ from the song), each tagged by a small audio
model, and a cautious rule on top.

Model
    CED-Tiny (Apache-2.0), an AudioSet tagger, exported to ONNX and quantised
    to int8 by the sherpa-onnx project (6 MB). It answers with 527
    probabilities per window; we read "A capella", "Chant", "Beatboxing" and
    the specific musical instruments (``data/audioset_vocal.json``).

Front-end
    A log-mel spectrogram computed with numpy, the same as CED was trained
    with (torchaudio MelSpectrogram, 16 kHz, n_fft 512, hop 160, 64 bands up
    to 8 kHz, no centring, dB with a 120 dB floor).

Decoding
    ``soundfile`` (libsndfile: MP3, FLAC, WAV, OGG, Opus), seeking straight to
    each window, so a song costs about 0.15 s. Files it cannot read (M4A, AAC,
    WMA) are marked "unreadable" and left to the title words.

Decision (measured on 30 freely licensed recordings: 9 of 12 a cappella found
— 6 as "vocal", 3 as "maybe" — and no false alarm among 18 with instruments;
docs/ARCHITECTURE.md has the details):
    vocal        at least 2 of 3 windows with "A capella" ≥ 0.10, and no
                 window with a specific instrument ≥ 0.30
    maybe        the same with "A capella" ≥ 0.03, or chanting (≥ 0.30) with
                 hardly any instrument (≤ 0.05)
    instruments  everything else

Everything here is optional: without numpy, onnxruntime, soundfile or the
model, :meth:`VocalDetector.available` is False and the app simply does not
offer the feature.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import sound

MODEL_NAME = "ced-tiny-int8"
MODEL_FOLDER = "ced-tiny"
MODEL_FILE = "model.int8.onnx"
# The model as the sherpa-onnx release ships it (audio-tagging-models).
MODEL_SHA256 = "73aa22e783115f6a4ae169b36089907e07d0fd44795595eddea9c1bfc74cc945"

SAMPLE_RATE = 16000
WINDOW_SECONDS = 10.0
POSITIONS = (0.2, 0.5, 0.8)

VOCAL_MIN = 0.10
MAYBE_MIN = 0.03
INSTRUMENT_MAX = 0.30
CHANT_MIN = 0.30
CHANT_INSTRUMENT_MAX = 0.05

# What each verdict means to the listener.
VERDICTS = {
    "vocal": "ווקאלי",
    "maybe": "אולי ווקאלי",
    "instruments": "עם כלי נגינה",
    "unreadable": "לא נבדק",
}

_CLASSES_FILE = Path(__file__).with_name("data") / "audioset_vocal.json"


@dataclass
class WindowScores:
    acapella: float
    instrument: float
    chant: float
    beatbox: float

    def as_list(self) -> list[float]:
        return [round(self.acapella, 4), round(self.instrument, 4), round(self.chant, 4), round(self.beatbox, 4)]


@dataclass
class VocalResult:
    verdict: str                      # vocal | maybe | instruments | unreadable | "" (not listened)
    windows: list[WindowScores] = field(default_factory=list)
    error: str = ""
    rhythm: dict | None = None        # tempo, pulse, loudness, energy (rhythm.py)
    profile: dict | None = None       # sound profile, speech and music (sound.summarize)
    edges: dict | None = None         # silence at the start and the end (sound.silence_edges)

    @property
    def acapella(self) -> float:
        return sum(w.acapella for w in self.windows) / len(self.windows) if self.windows else 0.0

    @property
    def instrument(self) -> float:
        return max((w.instrument for w in self.windows), default=0.0)


def decide(windows: list[WindowScores]) -> str:
    """The verdict for a song from its window scores (see the module doc)."""
    if not windows:
        return "unreadable"
    need = 2 if len(windows) >= 2 else 1
    no_instrument = max(w.instrument for w in windows) < INSTRUMENT_MAX
    if no_instrument and sum(w.acapella >= VOCAL_MIN for w in windows) >= need:
        return "vocal"
    if no_instrument and sum(w.acapella >= MAYBE_MIN for w in windows) >= need:
        return "maybe"
    if max(w.chant for w in windows) >= CHANT_MIN and max(w.instrument for w in windows) <= CHANT_INSTRUMENT_MAX:
        return "maybe"
    return "instruments"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class VocalDetector:
    """Loads lazily; safe to share between threads (one analysis at a time)."""

    def __init__(self, model_dirs: list[str | Path]):
        self.model_dirs = [Path(d) for d in model_dirs if d]
        self._lock = threading.Lock()
        self._session = None
        self._np = None
        self._sf = None
        self._fbank = None
        self._window = None
        self.load_error = ""
        try:
            self._classes = json.loads(_CLASSES_FILE.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover - the file ships with the app
            self._classes = {}

    # -- availability -------------------------------------------------------------
    def model_path(self) -> Path | None:
        for d in self.model_dirs:
            p = d / MODEL_FOLDER / MODEL_FILE
            if p.exists():
                return p
        return None

    @staticmethod
    def readers_present() -> bool:
        """What reading the windows needs (the tempo needs nothing more)."""
        try:
            import numpy  # noqa: F401
            import soundfile  # noqa: F401
        except Exception:
            return False
        return True

    def _load_readers(self) -> bool:
        if self._np is not None:
            return True
        try:
            import numpy as np
            import soundfile as sf
        except Exception as exc:  # noqa: BLE001
            self.load_error = f"{type(exc).__name__}: {exc}"
            return False
        self._np, self._sf = np, sf
        return True

    @staticmethod
    def libraries_present() -> bool:
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
            import soundfile  # noqa: F401
        except Exception:
            return False
        return True

    def available(self) -> bool:
        return self.model_path() is not None and self.libraries_present() and bool(self._classes)

    def status(self) -> dict:
        path = self.model_path()
        return {
            "model": MODEL_NAME,
            "model_found": path is not None,
            "libraries": self.libraries_present(),
            "available": self.available(),
            "loaded": self._session is not None,
            "error": self.load_error,
        }

    def unload(self) -> None:
        """Let the model go when the listening job is over (1.5.1)."""
        if self._lock.acquire(blocking=False):
            try:
                self._session = None
            finally:
                self._lock.release()

    def load(self) -> bool:
        if self._session is not None:
            return True
        path = self.model_path()
        if path is None:
            self.load_error = "the vocal model is not installed"
            return False
        try:
            import numpy as np
            import onnxruntime as ort
            import soundfile as sf

            options = ort.SessionOptions()
            # One thread: this runs in the background while music plays.
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            self._session = ort.InferenceSession(str(path), sess_options=options,
                                                 providers=["CPUExecutionProvider"])
            self._np, self._sf = np, sf
            self._fbank = _mel_filterbank(np)
            self._window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(512) / 512)).astype(np.float32)
            self.load_error = ""
            return True
        except Exception as exc:  # noqa: BLE001 - reported in the status
            self._session = None
            self.load_error = f"{type(exc).__name__}: {exc}"
            return False

    # -- listening ------------------------------------------------------------------
    def _features(self, x):
        np = self._np
        n_frames = 1 + (len(x) - 512) // 160
        idx = np.arange(512)[None, :] + 160 * np.arange(n_frames)[:, None]
        frames = x[idx] * self._window
        power = np.abs(np.fft.rfft(frames, n=512, axis=1)) ** 2
        mel = (power @ self._fbank).T
        db = 10.0 * np.log10(np.maximum(mel, 1e-10))
        db = np.maximum(db, db.max() - 120.0)
        return db.astype(np.float32)

    def _resample(self, x, sr: int):
        np = self._np
        if sr == SAMPLE_RATE or len(x) == 0:
            return x.astype(np.float32)
        n_out = int(round(len(x) * SAMPLE_RATE / sr))
        spectrum = np.fft.rfft(x)
        keep = n_out // 2 + 1
        out = np.zeros(keep, dtype=complex)
        m = min(keep, len(spectrum))
        out[:m] = spectrum[:m]
        return (np.fft.irfft(out, n_out) * (n_out / len(x))).astype(np.float32)

    def read_windows(self, path: str | Path) -> list:
        """Three mono 16 kHz windows of ten seconds (or the whole of a short
        song, padded)."""
        np, sf = self._np, self._sf
        out = []
        with sf.SoundFile(str(path)) as f:
            sr = f.samplerate
            frames = f.frames
            span = int(WINDOW_SECONDS * sr)
            if frames <= 0:
                raise ValueError("unknown length")
            if frames < 4 * span:  # under 40 s: the song itself, once
                data = f.read(dtype="float32", always_2d=True)
                starts = [None]
            else:
                starts = [int((frames - span) * p) for p in POSITIONS]
                data = None
            for start in starts:
                if start is not None:
                    f.seek(start)
                    data = f.read(span, dtype="float32", always_2d=True)
                mono = data.mean(axis=1) if data.ndim == 2 else data
                x = self._resample(np.asarray(mono, dtype=np.float32), sr)
                n = int(WINDOW_SECONDS * SAMPLE_RATE)
                if len(x) > n:  # a short song read whole: its middle ten seconds
                    start_at = (len(x) - n) // 2
                    x = x[start_at:start_at + n]
                out.append(np.pad(x, (0, max(0, n - len(x)))))
        return out

    def window_probs(self, x):
        """The 527 AudioSet probabilities of one window."""
        return self._session.run(None, {"feats": self._features(x)[None]})[0][0]

    def score_window(self, x, probs=None) -> WindowScores:
        np = self._np
        if probs is None:
            probs = self.window_probs(x)
        c = self._classes
        instruments = c.get("instruments") or []
        return WindowScores(
            acapella=float(probs[c["a_capella"]]),
            instrument=float(np.max(probs[instruments])) if instruments else 0.0,
            chant=float(probs[c["chant"]]),
            beatbox=float(probs[c["beatboxing"]]),
        )

    def analyze(self, path: str | Path, *, listen: bool = True) -> VocalResult:
        """Listen to one song: singing without instruments (``listen``) and
        its tempo and energy. Never raises: a file that cannot be read gets
        the verdict "unreadable"."""
        from .rhythm import analyze_windows

        with self._lock:
            if listen and not self.load():
                return VocalResult("unreadable", error=self.load_error)
            if not self._load_readers():
                return VocalResult("unreadable", error=self.load_error)
            try:
                audio = self.read_windows(path)
                probs = [self.window_probs(x) for x in audio] if listen else []
                windows = [self.score_window(x, p) for x, p in zip(audio, probs)]
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the job
                return VocalResult("unreadable", error=f"{type(exc).__name__}: {exc}")
            try:
                rhythm = analyze_windows(audio, SAMPLE_RATE)
            except Exception:  # noqa: BLE001 - the tempo is a bonus
                rhythm = None
            profile = sound.summarize(probs) if probs else None
            edges = sound.silence_edges(path, self._sf, self._np)
            return VocalResult(decide(windows) if listen else "", windows, rhythm=rhythm,
                               profile=profile, edges=edges)


def _mel_filterbank(np, n_freqs: int = 257, f_min: float = 0.0, f_max: float = 8000.0, n_mels: int = 64,
                    sr: int = SAMPLE_RATE):
    """torchaudio's HTK mel filterbank, as a [n_freqs, n_mels] matrix."""
    def hz_to_mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel_to_hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    all_freqs = np.linspace(0, sr // 2, n_freqs)
    m_pts = np.linspace(hz_to_mel(f_min), hz_to_mel(f_max), n_mels + 2)
    f_pts = mel_to_hz(m_pts)
    f_diff = f_pts[1:] - f_pts[:-1]
    slopes = f_pts[None, :] - all_freqs[:, None]
    down = -slopes[:, :-2] / f_diff[:-1]
    up = slopes[:, 2:] / f_diff[1:]
    return np.maximum(0.0, np.minimum(down, up)).astype(np.float32)
