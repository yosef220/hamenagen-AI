"""1.1: the listener's corrections, album/folder propagation and the vocal
detector (its rule, its listening loop with a stand-in model, and how its
verdicts reach the library)."""

import json
import os
import time

import pytest

from hamenagen.service import PlayerService
from hamenagen.vocal import VocalDetector, WindowScores, decide

SONG_BYTES = b"\0" * (70 * 1024)


def _library(root, names):
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).write_bytes(SONG_BYTES)
    return root


def _service(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")
    service.settings.use_embeddings = False
    service.classifier.embedding = None
    return service


def _by_title(service):
    return {t.title: t for t in service.index.all_tracks()}


# ------------------------------------------------------------------ corrections
def test_a_chosen_topic_survives_rescans_and_reclassification(tmp_path):
    music = _library(tmp_path / "music", ["זמר - ניגון ערב.mp3", "זמר - מנוחה ושמחה.mp3"])
    service = _service(tmp_path)
    service.rescan([str(music)])
    song = _by_title(service)["ניגון ערב"]
    assert song.topic is None

    out = service.set_track_topic(song.id, "חתונה")
    assert out["ok"] and out["track"]["topic"] == "חתונה" and out["track"]["topic_source"] == "user"
    assert out["track"]["topic_chosen"] is True

    # The file changes and is scanned again; everything is reclassified.
    path = music / "זמר - ניגון ערב.mp3"
    path.write_bytes(SONG_BYTES + b"x")
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert service.rescan([str(music)])["updated"] == 1
    service.reclassify_all()
    assert _by_title(service)["ניגון ערב"].topic == "חתונה"

    # "No topic" is a choice too, even for a song the lexicon knows.
    known = _by_title(service)["מנוחה ושמחה"]
    service.set_track_topic(known.id, "")
    assert _by_title(service)["מנוחה ושמחה"].topic is None
    # Back to automatic.
    service.set_track_topic(known.id, None)
    assert _by_title(service)["מנוחה ושמחה"].topic == "שבת"
    service.close()


def test_unplaced_songs_follow_their_album_and_folder(tmp_path):
    music = tmp_path / "music"
    _library(music / "אלבום אחד", [
        "זמר - יה ריבון.mp3", "זמר - מנוחה ושמחה.mp3", "זמר - צור משלו.mp3", "זמר - ניגון בלי שם.mp3",
    ])
    _library(music / "מעורב", ["א - יה ריבון.mp3", "ב - נרות חנוכה.mp3", "ג - שיר אחר.mp3"])
    service = _service(tmp_path)
    result = service.rescan([str(music)])
    songs = {(t.title, os.path.basename(os.path.dirname(t.path))): t for t in service.index.all_tracks()}
    nameless = songs[("ניגון בלי שם", "אלבום אחד")]
    assert nameless.topic == "שבת" and nameless.topic_source == "folder"
    assert "אלבום אחד" in nameless.topic_note
    assert result["propagated"] >= 1
    # A mixed folder (no clear majority) teaches nothing.
    assert songs[("שיר אחר", "מעורב")].topic is None

    # The listener's "no topic" is not overridden by the folder.
    service.set_track_topic(nameless.id, "")
    assert service.index.get(nameless.id).topic is None
    service.close()


def test_vocal_marks_add_and_remove_the_vocal_topic(tmp_path):
    music = _library(tmp_path / "music", ["זמר - מנוחה ושמחה.mp3", "מקהלה - שיר אקפלה.mp3"])
    service = _service(tmp_path)
    service.rescan([str(music)])
    songs = _by_title(service)
    shabbat, acapella = songs["מנוחה ושמחה"], songs["שיר אקפלה"]
    assert acapella.topic == "ווקאלי"

    out = service.set_track_vocal(shabbat.id, True)
    assert out["track"]["topic"] == "שבת" and "ווקאלי" in out["track"]["tags"] and out["track"]["vocal"] == "yes"
    service.set_track_vocal(acapella.id, False)  # the title says so, the listener knows better
    t = service.index.get(acapella.id)
    assert t.topic is None and "ווקאלי" not in t.tag_list
    service.set_track_vocal(acapella.id, None)
    assert service.index.get(acapella.id).topic == "ווקאלי"
    service.close()


# ------------------------------------------------------------------ the detector
def _windows(*acapella, instrument=0.0, chant=0.0):
    return [WindowScores(a, instrument, chant, 0.0) for a in acapella]


def test_the_vocal_rule_is_cautious():
    assert decide(_windows(0.2, 0.3, 0.01)) == "vocal"          # two clear windows
    assert decide(_windows(0.2, 0.3, 0.5, instrument=0.4)) == "instruments"  # an instrument is heard
    assert decide(_windows(0.05, 0.04, 0.0)) == "maybe"
    assert decide(_windows(0.2, 0.0, 0.0)) == "instruments"     # one window is not enough
    assert decide(_windows(0.0, 0.0, 0.0, chant=0.5)) == "maybe"
    assert decide(_windows(0.0, 0.0, 0.0, chant=0.5, instrument=0.2)) == "instruments"
    assert decide([]) == "unreadable"
    assert decide(_windows(0.15)) == "vocal"                    # a short song: one window


class _FakeSession:
    """Stands in for the ONNX model: every window sounds like a choir."""

    def __init__(self, classes, acapella):
        self.classes, self.acapella = classes, acapella
        self.calls = 0

    def run(self, _outputs, feeds):
        import numpy as np

        feats = feeds["feats"]
        assert feats.shape[:2] == (1, 64) and feats.shape[2] > 900  # 10 s of 10 ms frames
        self.calls += 1
        probs = np.zeros((1, self.classes["classes"]), dtype=np.float32)
        probs[0, self.classes["a_capella"]] = self.acapella
        return [probs]


def _detector_with_fake_model(tmp_path, acapella):
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    from hamenagen import vocal as vocal_mod

    d = VocalDetector([tmp_path])
    d._np, d._sf = np, sf
    d._fbank = vocal_mod._mel_filterbank(np)
    d._window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(512) / 512)).astype(np.float32)
    d._session = _FakeSession(d._classes, acapella)
    return d, np, sf


def test_listening_reads_three_windows_of_a_long_song(tmp_path):
    d, np, sf = _detector_with_fake_model(tmp_path, acapella=0.4)
    path = tmp_path / "song.wav"
    t = np.arange(44100 * 60) / 44100.0  # one minute, 44.1 kHz stereo
    sf.write(path, np.stack([np.sin(2 * np.pi * 220 * t), np.sin(2 * np.pi * 330 * t)], axis=1) * 0.2, 44100)
    result = d.analyze(path)
    assert result.verdict == "vocal" and len(result.windows) == 3 and d._session.calls == 3
    assert result.acapella == pytest.approx(0.4, abs=1e-6)


def test_short_or_unreadable_files(tmp_path):
    d, np, sf = _detector_with_fake_model(tmp_path, acapella=0.0)
    short = tmp_path / "short.wav"
    sf.write(short, np.zeros(16000 * 5, dtype=np.float32), 16000)
    r = d.analyze(short)
    assert r.verdict == "instruments" and len(r.windows) == 1
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not audio at all")
    r = d.analyze(broken)
    assert r.verdict == "unreadable" and r.error


def test_the_front_end_matches_the_trained_shape(tmp_path):
    d, np, _ = _detector_with_fake_model(tmp_path, acapella=0.0)
    x = (np.random.default_rng(0).standard_normal(160000) * 0.1).astype(np.float32)
    feats = d._features(x)
    assert feats.shape == (64, 997) and feats.dtype == np.float32
    assert feats.max() - feats.min() <= 120.0 + 1e-3
    y = d._resample(np.ones(44100, dtype=np.float32), 44100)
    assert len(y) == 16000


# ------------------------------------------------------------------ verdicts in the library
def _heard(service, track, verdict, acapella):
    service.index.save_analysis(track.id, {
        "model": "ced-tiny-int8", "verdict": verdict, "acapella": acapella, "instrument": 0.0,
        "windows": json.dumps([[acapella, 0, 0, 0]] * 3), "mtime": track.mtime, "size": track.size,
        "analyzed_at": "2026-11-11T12:00:00",
    })


def test_detected_songs_wait_for_the_listener_unless_allowed(tmp_path):
    music = _library(tmp_path / "music", ["א - ניגון ראשון.mp3", "ב - ניגון שני.mp3", "ג - אקפלה בבוקר.mp3"])
    service = _service(tmp_path)
    service.rescan([str(music)])
    songs = _by_title(service)
    _heard(service, songs["ניגון ראשון"], "vocal", 0.6)
    _heard(service, songs["ניגון שני"], "maybe", 0.05)
    _heard(service, songs["אקפלה בבוקר"], "vocal", 0.7)  # its name already says so

    review = service.vocal_review()
    assert [t["title"] for t in review["tracks"]] == ["ניגון ראשון", "ניגון שני"]
    assert review["tracks"][0]["vocal"] == "vocal"
    # Not counted as vocal until confirmed…
    assert "ווקאלי" not in (service.index.get(songs["ניגון ראשון"].id).tag_list + [service.index.get(songs["ניגון ראשון"].id).topic])

    # …unless the listener lets detected songs in.
    service.update_settings({"vocal_auto_include": True})
    t = service.index.get(songs["ניגון ראשון"].id)
    assert t.topic == "ווקאלי" and t.topic_source == "audio" and "מהשמע" in t.topic_note
    assert service.index.get(songs["ניגון שני"].id).topic is None  # "maybe" never counts by itself
    service.update_settings({"vocal_auto_include": False})
    assert service.index.get(songs["ניגון ראשון"].id).topic is None

    # Confirming moves songs out of the review list and into the topic.
    service.confirm_vocal([songs["ניגון ראשון"].id], True)
    service.confirm_vocal([songs["ניגון שני"].id], False)
    assert service.vocal_review()["count"] == 0
    assert service.index.get(songs["ניגון ראשון"].id).topic == "ווקאלי"
    assert service.vocal_status()["vocal"] == 2
    service.close()


def test_vocal_status_without_the_model(tmp_path):
    service = _service(tmp_path)
    st = service.vocal_status()
    assert st["enabled"] is True and st["available"] is False and st["model_found"] is False
    assert service.analyze_vocal()["reason"] == "unavailable"
    service.close()
