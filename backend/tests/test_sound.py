"""The sound profile (sound.py): speech or song, silence at the edges, how
loud, how alike — and what it keeps out of mixes."""

from __future__ import annotations

import math

import pytest
from hamenagen import sound
from hamenagen.index_db import MusicIndex
from hamenagen.models import Track

np = pytest.importorskip("numpy")


def test_speech_needs_strong_speech_not_weaker_than_the_music():
    # Values measured on real recordings (sound.py's note).
    assert sound.is_speech({"speech": 0.82, "music": 0.0})            # a reading
    assert sound.is_speech({"speech": 0.63, "music": 0.58})           # a talk over music
    assert not sound.is_speech({"speech": 0.03, "music": 0.82})       # a song (a few words in the intro)
    assert not sound.is_speech({"speech": 0.55, "music": 0.7})        # rap: music louder
    assert not sound.is_speech(None) and not sound.is_speech({})


def test_words_in_the_name_and_the_listener_decide_first():
    assert sound.is_speech({}, "שיעור בגמרא - הרב כהן")
    assert sound.is_speech({}, "דברי פתיחה")
    assert not sound.is_speech({}, "ניגון שמחה")
    assert not sound.is_speech({"speech": 0.9, "music": 0.0}, "", {"speech": 0})
    assert sound.is_speech({"speech": 0.0, "music": 0.9}, "", {"speech": 1})


def test_summarize_keeps_the_profile_and_the_middle_window():
    p = np.zeros((3, sound.CLASSES), dtype=np.float32)
    p[:, 137] = (0.8, 0.7, 0.9)        # music
    p[:, 0] = (0.9, 0.02, 0.01)        # speech only in the spoken intro
    out = sound.summarize(p)
    assert out["profile_v"] == sound.PROFILE_VERSION and out["speech"] == pytest.approx(0.02)
    assert out["music"] == pytest.approx(0.8)
    v = sound.unpack(out["profile"])
    assert v.shape == (sound.CLASSES,) and v[137] == pytest.approx(0.8, abs=1e-3)
    assert sound.unpack(b"bad") is None and sound.summarize([]) == {}


def test_similarity_compares_the_music_not_the_noise():
    a = np.zeros(sound.CLASSES, dtype=np.float32)
    b = a.copy()
    c = a.copy()
    a[[137, 140, 143]] = (0.8, 0.5, 0.4)       # music, guitar, acoustic guitar
    b[[137, 140, 143]] = (0.7, 0.45, 0.5)
    c[[137, 158, 239]] = (0.8, 0.6, 0.5)       # music, synthesizer, electronic
    a[300] = c[300] = 0.9                       # the same noise class: ignored
    assert sound.similarity(a, b) > 0.95 > sound.similarity(a, c)
    assert sound.similarity(a, None) == 0.0
    assert sound.facets(c)["electronic"] == pytest.approx(0.6)


def test_loud_songs_are_turned_down_and_quiet_ones_left():
    assert sound.gain_db(-9.0) == -5.0
    assert sound.gain_db(-20.0) == 0.0
    assert sound.gain_db(0.0) == -12.0          # never more than 12 dB
    assert sound.gain_db(None) == 0.0 and sound.gain_db(float("nan")) == 0.0


def test_silence_at_the_edges(tmp_path):
    sf = pytest.importorskip("soundfile")
    sr = 22050

    def tone(seconds):
        t = np.arange(int(seconds * sr)) / sr
        return 0.3 * np.sin(2 * math.pi * 440 * t)

    path = tmp_path / "song.wav"
    sf.write(path, np.concatenate([np.zeros(int(2.0 * sr)), tone(30), np.zeros(int(4.0 * sr))]), sr)
    edges = sound.silence_edges(path, sf, np)
    assert edges["lead"] == pytest.approx(2.0 - sound.LEAD_KEEP, abs=0.06)
    assert edges["tail"] == pytest.approx(4.0 - sound.TAIL_KEEP, abs=0.06)

    tight = tmp_path / "tight.wav"
    sf.write(tight, np.concatenate([np.zeros(int(0.3 * sr)), tone(20), np.zeros(int(0.5 * sr))]), sr)
    assert sound.silence_edges(tight, sf, np) == {"lead": 0.0, "tail": 0.0}   # too short to skip
    assert sound.silence_edges(tmp_path / "missing.wav", sf, np) is None


def test_spoken_recordings_disliked_songs_and_kept_apart_folders_stay_out_of_mixes(tmp_path):
    idx = MusicIndex(tmp_path / "lib.db")
    idx.upsert_many([
        Track(id="song", path="/m/songs/a.mp3", title="שיר", topic="שבת"),
        Track(id="talk", path="/m/talks/b.mp3", title="שיעור", topic="שבת"),
        Track(id="meh", path="/m/songs/c.mp3", title="לא אהוב", topic="שבת"),
        Track(id="kids", path="/m/kids/d.mp3", title="ילדים", topic="שבת"),
    ])
    idx.set_kind("talk", "speech")
    idx.set_override("meh", disliked=1)
    idx.isolated_folders = ["/m/kids"]
    assert [t.id for t in idx.by_topic("שבת")] == ["song"]
    assert {t.id for t in idx.by_topic("שבת", mix=False)} == {"song", "talk", "meh", "kids"}
    assert [t.id for t in idx.mixable_tracks()] == ["song"]
    assert {t.id for t in idx.random(10)} == {"song"}
    assert [t.id for t in idx.list_tracks(kind="speech")["tracks"]] == ["talk"]
    assert idx.speech_count() == 1 and idx.disliked_ids() == {"meh"}
    # Undoing a decision removes it.
    idx.set_override("meh", disliked=None)
    assert idx.get_override("meh") is None
    idx.close()


def test_the_real_model_tells_a_talk_from_a_song(tmp_path):
    """With the audio model and a few real recordings (when present)."""
    from pathlib import Path

    from hamenagen.vocal import VocalDetector

    roots = [Path(p) for p in (
        "/tmp/claude-0/-home-user-hamenagen-AI/08d4f886-f518-51d1-ab07-4a8aea1be72c/scratchpad",
    )]
    root = next((r for r in roots if (r / "audio-models").is_dir()), None)
    if root is None:
        pytest.skip("no model here")
    det = VocalDetector([root / "audio-models"])
    if not det.load():
        pytest.skip(det.load_error)
    talk = next(iter((root / "speech").glob("*.mp3")), None)
    song = next(iter((root / "full_mp3").glob("*Hamakor*")), None)
    if talk is None or song is None:
        pytest.skip("no recordings here")
    t, s = det.analyze(talk), det.analyze(song)
    assert sound.is_speech(t.profile) and not sound.is_speech(s.profile)
    assert t.edges is not None and s.profile["profile_v"] == sound.PROFILE_VERSION
