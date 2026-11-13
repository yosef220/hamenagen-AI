"""Requests by voice (voice.py): features, the download, the recognizer."""

from __future__ import annotations

import base64
import hashlib
import io
import math
from pathlib import Path

import pytest
from hamenagen import voice

np = pytest.importorskip("numpy")

SCRATCH = Path("/tmp/claude-0/-home-user-hamenagen-AI/08d4f886-f518-51d1-ab07-4a8aea1be72c/scratchpad/asr")


def test_fbank_frames_and_a_tone_in_the_right_band():
    sr = 16000
    t = np.arange(sr) / sr
    feats = voice.fbank(0.3 * np.sin(2 * math.pi * 1000 * t), np)
    assert feats.shape == (100, 80)                       # 10 ms frames, centred
    banks = voice._mel_banks(np)
    peak = int(np.argmax(feats[50]))
    centre = int(np.argmax(banks[:, int(1000 / (sr / 512))]))
    assert abs(peak - centre) <= 1
    assert voice.fbank(np.zeros(0), np).shape == (0, 80)


def test_tokens_become_words_and_requests_lose_punctuation():
    assert voice.detokenize(["▁שי", "רי", "▁שבת", "<unk>"]) == "שירי שבת"
    assert voice.clean_request("שירי שבת, בבקשה.") == "שירי שבת בבקשה"


def test_resample_keeps_the_length_in_seconds():
    assert len(voice.resample(np.zeros(48000), 48000, np)) == 16000


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_download_checks_every_file(tmp_path, monkeypatch):
    blobs = {path: f"data of {name}".encode() for name, (path, _) in voice.FILES.items()}
    monkeypatch.setattr(voice, "FILES", {name: (path, hashlib.sha256(blobs[path]).hexdigest())
                                         for name, (path, _) in voice.FILES.items()})
    seen = []

    def opener(req, timeout=0):
        return _Resp(blobs[req.full_url.split(f"{voice.REVISION}/", 1)[1]])

    target = voice.install(tmp_path, on_progress=seen.append, opener=opener)
    assert target == tmp_path / voice.MODEL_FOLDER and (target / "model.json").is_file()
    assert seen and seen[-1]["file"] == len(voice.FILES)

    # One file that does not match: nothing is kept.
    def bad(req, timeout=0):
        return _Resp(b"something else")

    other = tmp_path / "other"
    with pytest.raises(RuntimeError):
        voice.install(other, opener=bad)
    assert not (other / voice.MODEL_FOLDER).exists() and not list(other.glob("voice-*"))


def test_without_the_model_the_service_says_so(tmp_path):
    from hamenagen.service import PlayerService

    svc = PlayerService(data_dir=tmp_path / "data")
    st = svc.voice_status()
    assert st["available"] is False and st["download_mb"] > 0
    assert svc.voice_recognize("")["reason"] == "no-model"
    svc.close()


def test_the_real_model_hears_hebrew(tmp_path):
    """With the model and a recording from the Kan corpus (when present)."""
    sf = pytest.importorskip("soundfile")
    pytest.importorskip("onnxruntime")
    if not (SCRATCH / "models" / voice.MODEL_FOLDER).is_dir() or not (SCRATCH / "he" / "s04.wav").is_file():
        pytest.skip("no model here")
    from hamenagen.service import PlayerService

    svc = PlayerService(data_dir=tmp_path / "data")
    svc.voice = voice.SpeechRecognizer([SCRATCH / "models"])
    x, sr = sf.read(SCRATCH / "he" / "s04.wav", dtype="float32", always_2d=True)
    pcm = (np.clip(x.mean(axis=1), -1, 1) * 32767).astype("<i2").tobytes()
    out = svc.voice_recognize(base64.b64encode(pcm).decode(), sr)
    assert out["ok"] and out["request"] == "יכול להיות"
    svc.close()


def test_the_offline_editions_model_is_found_in_its_own_folder(tmp_path, monkeypatch):
    from hamenagen.service import PlayerService

    own = tmp_path / "voice-models"
    (own / voice.MODEL_FOLDER).mkdir(parents=True)
    for name in voice.FILES:
        (own / voice.MODEL_FOLDER / name).write_text("x")
    monkeypatch.setenv("HAMENAGEN_VOICE_MODELS_DIR", str(own))
    svc = PlayerService(data_dir=tmp_path / "data")
    st = svc.voice_status()
    assert st["available"] and st["bundled"]
    svc.close()


def test_a_long_spoken_sentence_finds_the_song_inside_it(tmp_path):
    from hamenagen.models import Track
    from hamenagen.service import PlayerService

    svc = PlayerService(data_dir=tmp_path / "data")
    svc.index.upsert_many([
        Track(id="j", path="/m/j.mp3", title="ירושלים של זהב", artist="נעמי"),
        Track(id="k", path="/m/k.mp3", title="שיר לציון", artist="אחים"),
    ])
    said = "תשמע אני רוצה עכשיו ירושלים של זהב כי זה יפה"
    typed = svc.handle_request(said)
    assert not typed["tracks"]                       # typed: every word counts, as before
    spoken = svc.handle_request(said, spoken=True)
    assert [t["id"] for t in spoken["tracks"]] == ["j"]
    assert "ירושלים של זהב" in spoken["understood"] and spoken["note"].startswith("שמעתי")
    svc.close()
