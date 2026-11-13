"""Requests by voice: Hebrew speech recognition on the computer, offline.

The microphone button records a few seconds in the window; the samples come
here and become text, which is then handled like a typed request.

The model is ivrit.ai's Hebrew streaming Zipformer2 transducer
(zipformer2-66m-streaming-he, by Yakov Kolani, CC-BY-4.0), int8 ONNX, 72 MB,
run with onnxruntime (already in the app for the vocal detector) — no new
library and no internet. On real Hebrew recordings (Kan, ivrit.ai) it
writes the sentence almost word for word, in a third of a second. Whisper
models small enough to ship were measured far weaker in Hebrew.

Everything a recognizer needs is here, in numpy:

* Kaldi filter-bank features (80 mel bins, 25 ms frames every 10 ms,
  Povey window, the same settings the model was trained with);
* the streaming encoder, fed 1.28 s chunks with its caches carried over
  (their names and shapes are in the model's own config);
* greedy transducer search with the decoder and the joiner.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

MODEL_NAME = "zipformer2-66m-streaming-he"
MODEL_FOLDER = "voice-he"
# file → (path in the model repository, SHA-256), at a pinned revision.
FILES = {
    "encoder.int8.onnx": ("sherpa-onnx/encoder.int8.onnx",
                          "6c6febcb74a09435315a1d872a6539f6e7fc2c333533f14c74edc0e85c49ffcd"),
    "decoder.int8.onnx": ("sherpa-onnx/decoder.int8.onnx",
                          "feb03e7c8aa761593a9284a6fa1e91259be3702de75f630062256c1a59c5a906"),
    "joiner.int8.onnx": ("sherpa-onnx/joiner.int8.onnx",
                         "1d2c6d8e6dabc5eb52de52e95718e9bdfbffbfe7ead3808fb5ffd74e83bd9cae"),
    "tokens.txt": ("sherpa-onnx/tokens.txt", "e4ebb5e72a6aeef47437a55fa2308ebbedb7c51c557de7a89bf965c23ea9af4a"),
    "config.json": ("onnx/config.json", "6ad75405069d306cf96f1642e8093f7642773f40082c39a0ce7a3d270b1db920"),
}
REVISION = "ee769a2a13b887f91572eec349458bfb0fe79e7a"
SOURCE = "https://huggingface.co/ivrit-ai/zipformer2-66m-streaming-he"
LICENCE = "CC-BY-4.0"
CREDIT = "zipformer2-66m-streaming-he, Yakov Kolani; ivrit.ai (CC-BY-4.0)"
DOWNLOAD_MB = 73


def install(target_root, on_progress=None, opener=None) -> Path:
    """Download the model once into ``target_root/voice-he`` (every file
    checked against its pinned SHA-256; nothing is kept if one differs)."""
    import hashlib
    import os
    import shutil
    import tempfile
    import urllib.request

    target = Path(target_root) / MODEL_FOLDER
    open_ = opener or urllib.request.urlopen
    total = sum(1 for _ in FILES)
    Path(target_root).mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="voice-", dir=str(Path(target_root))))
    try:
        for n, (name, (path, digest)) in enumerate(FILES.items(), 1):
            url = f"{SOURCE}/resolve/{REVISION}/{path}"
            req = urllib.request.Request(url, headers={"User-Agent": "hamenagen"})
            h = hashlib.sha256()
            with open_(req, timeout=60) as resp, open(tmp / name, "wb") as out:
                size = int(resp.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    block = resp.read(1 << 16)
                    if not block:
                        break
                    out.write(block)
                    h.update(block)
                    got += len(block)
                    if on_progress and size:
                        on_progress({"file": n, "files": total, "done": got, "size": size})
            if h.hexdigest() != digest:
                raise RuntimeError(f"הקובץ {name} שירד לא תואם לחתימה שלו")
        (tmp / "model.json").write_text(json.dumps({
            "name": MODEL_NAME, "source": SOURCE, "revision": REVISION, "licence": LICENCE, "credit": CREDIT,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        os.replace(tmp, target)
        return target
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


SAMPLE_RATE = 16000
MAX_SECONDS = 15.0


# ------------------------------------------------------------------ features
_FBANK_CACHE: dict = {}


def _mel_banks(np, num_bins: int = 80, fft: int = 512, sr: int = SAMPLE_RATE,
               low: float = 20.0, high: float = -400.0):
    key = (num_bins, fft, sr, low, high)
    if key in _FBANK_CACHE:
        return _FBANK_CACHE[key]
    nyquist = sr / 2
    high = nyquist + high if high <= 0 else high

    def mel(f):
        return 1127.0 * np.log(1.0 + f / 700.0)

    lo, hi = mel(low), mel(high)
    delta = (hi - lo) / (num_bins + 1)
    freqs = np.arange(fft // 2) * (sr / fft)
    m = mel(freqs)
    banks = np.zeros((num_bins, fft // 2), dtype=np.float32)
    for b in range(num_bins):
        left, center, right = lo + b * delta, lo + (b + 1) * delta, lo + (b + 2) * delta
        up = (m - left) / (center - left)
        down = (right - m) / (right - center)
        w = np.where((m > left) & (m <= center), up, np.where((m > center) & (m < right), down, 0.0))
        banks[b] = w
    _FBANK_CACHE[key] = banks
    return banks


def fbank(samples, np, sr: int = SAMPLE_RATE, num_bins: int = 80):
    """Kaldi-style log mel filter-bank features, ``frames × num_bins``.

    snip_edges off (frames centred, edges reflected), no dither, the DC
    removed, pre-emphasis 0.97, Povey window, power spectrum, 20 Hz to
    Nyquist − 400 Hz. ``samples`` are floats in −1…1."""
    x = np.asarray(samples, dtype=np.float32)
    shift, length, fft = int(sr * 0.010), int(sr * 0.025), 512
    n = len(x)
    frames = (n + shift // 2) // shift
    if frames <= 0:
        return np.zeros((0, num_bins), dtype=np.float32)
    starts = np.arange(frames) * shift + shift // 2 - length // 2
    idx = starts[:, None] + np.arange(length)[None, :]
    idx = np.where(idx < 0, -idx - 1, idx)
    idx = np.where(idx >= n, 2 * n - 1 - idx, idx)
    idx = np.clip(idx, 0, n - 1)
    w = x[idx].astype(np.float64)
    w -= w.mean(axis=1, keepdims=True)
    pre = w.copy()
    pre[:, 1:] -= 0.97 * w[:, :-1]
    pre[:, 0] -= 0.97 * w[:, 0]
    win = np.power(0.5 - 0.5 * np.cos(2 * math.pi * np.arange(length) / (length - 1)), 0.85)
    spec = np.fft.rfft(pre * win, n=fft, axis=1)
    power = (spec.real ** 2 + spec.imag ** 2)[:, : fft // 2]
    energies = power @ _mel_banks(np, num_bins, fft, sr).T.astype(np.float64)
    return np.log(np.maximum(energies, np.finfo(np.float32).eps)).astype(np.float32)


def resample(samples, rate: int, np):
    """Linear resampling to 16 kHz (the window records at 16 kHz already;
    this is for files and other rates)."""
    x = np.asarray(samples, dtype=np.float32)
    if rate == SAMPLE_RATE or len(x) == 0:
        return x
    n = int(round(len(x) * SAMPLE_RATE / rate))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


# ------------------------------------------------------------------ model
class SpeechRecognizer:
    """Hebrew speech to text with the Zipformer2 transducer (see the module
    note). ``load`` is cheap to call again; ``recognize`` is thread-safe."""

    def __init__(self, model_dirs):
        self.model_dirs = [Path(d) for d in model_dirs if d]
        self.load_error = ""
        self._lock = threading.Lock()
        self._sessions = None
        self._tokens: list[str] = []
        self._config: dict = {}

    def model_dir(self) -> Path | None:
        for d in self.model_dirs:
            folder = d / MODEL_FOLDER
            if all((folder / f).is_file() for f in FILES):
                return folder
        return None

    @property
    def available(self) -> bool:
        return self.model_dir() is not None

    @property
    def loaded(self) -> bool:
        return self._sessions is not None

    def load(self) -> bool:
        if self._sessions is not None:
            return True
        folder = self.model_dir()
        if folder is None:
            self.load_error = "המודל לזיהוי דיבור עוד לא במחשב."
            return False
        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            opts.inter_op_num_threads = 1
            sess = {name: ort.InferenceSession(str(folder / f"{name}.int8.onnx"), sess_options=opts,
                                               providers=["CPUExecutionProvider"])
                    for name in ("encoder", "decoder", "joiner")}
            config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
            tokens = {}
            for line in (folder / "tokens.txt").read_text(encoding="utf-8").splitlines():
                parts = line.rsplit(" ", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    tokens[int(parts[1])] = parts[0]
            self._tokens = [tokens.get(i, "") for i in range(max(tokens) + 1)]
            self._config = config
            self._sessions = sess
            self.load_error = ""
            return True
        except Exception as exc:  # noqa: BLE001 - reported to the window
            self.load_error = f"המודל לזיהוי דיבור לא נטען: {exc}"
            return False

    def _initial_states(self, np) -> dict:
        out = {}
        for st in self._config["states"]:
            dtype = np.int64 if st.get("type") == "int64" else np.float32
            out[st["name"]] = np.zeros(st["shape"], dtype=dtype)
        if "processed_lens" not in out:
            out["processed_lens"] = np.zeros([1], dtype=np.int64)
        return out

    def recognize(self, samples, rate: int = SAMPLE_RATE) -> str:
        """The words in ``samples`` (mono floats −1…1), as plain text."""
        import numpy as np

        if not self.load():
            raise RuntimeError(self.load_error)
        x = resample(samples, rate, np)[: int(MAX_SECONDS * SAMPLE_RATE)]
        # Silence after the speech, so the last words leave the encoder.
        x = np.concatenate([x, np.zeros(int(1.5 * SAMPLE_RATE), dtype=np.float32)])
        feats = fbank(x, np)
        cfg = self._config
        T, step = int(cfg["T"]), int(cfg["decode_chunk_len"])
        ctx, blank = int(cfg.get("context_size", 2)), int(cfg.get("blank_id", 0))
        with self._lock:
            enc, dec, join = (self._sessions[k] for k in ("encoder", "decoder", "joiner"))
            states = self._initial_states(np)
            state_names = [i.name for i in enc.get_inputs() if i.name != "x"]
            out_names = [o.name for o in enc.get_outputs()]
            hyp = [blank] * ctx
            dec_out = dec.run(None, {"y": np.array([hyp[-ctx:]], dtype=np.int64)})[0]
            # Whole chunks only: the last one is filled with silence.
            need = T + step * max(0, math.ceil((len(feats) - T) / step))
            if len(feats) < need:
                pad = np.full((need - len(feats), feats.shape[1]), float(feats.min()), np.float32)
                feats = np.concatenate([feats, pad])
            for start in range(0, len(feats) - T + 1, step):
                chunk = feats[start:start + T][None, :, :]
                feed = {"x": chunk, **{n: states[n] for n in state_names}}
                res = enc.run(out_names, feed)
                enc_out = res[0][0]
                for name, value in zip(out_names[1:], res[1:]):
                    states[name.removeprefix("new_")] = value
                for frame in enc_out:
                    logits = join.run(None, {"encoder_out": frame[None, :], "decoder_out": dec_out})[0][0]
                    y = int(np.argmax(logits))
                    if y != blank:
                        hyp.append(y)
                        dec_out = dec.run(None, {"y": np.array([hyp[-ctx:]], dtype=np.int64)})[0]
        return detokenize([self._tokens[i] for i in hyp[ctx:] if i < len(self._tokens)])


def detokenize(pieces: list[str]) -> str:
    text = "".join(p for p in pieces if p and not (p.startswith("<") and p.endswith(">")))
    return " ".join(text.replace("▁", " ").split())


def clean_request(text: str) -> str:
    """What was heard, as a request: no sentence punctuation, one line."""
    import re

    text = re.sub(r"[.,!?;:…\"“”]+", " ", text or "")
    return " ".join(text.split())
