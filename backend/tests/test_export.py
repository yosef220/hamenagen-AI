"""Copying songs to an MP3 player (export.py) and cutting a ringtone (ringtone.py)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hamenagen import export, ringtone, tags

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")
pytest.importorskip("mutagen")
HAVE_FFMPEG = bool(shutil.which("ffmpeg"))


def _tone(path, seconds=2.0, fmt=None):
    t = np.arange(int(8000 * seconds)) / 8000
    sf.write(path, 0.2 * np.sin(2 * np.pi * 440 * t), 8000, format=fmt)
    return path


def test_names_every_player_accepts():
    assert export.clean_name('שיר: "אחד"?/שניים') == "שיר אחד שניים"
    assert export.clean_name("CON") == "CON_"
    assert export.clean_name("  ...  ") == "שיר"
    assert len(export.clean_name("א" * 300)) == export.NAME_MAX


def _songs(tmp_path, n=3):
    out = []
    for i in range(n):
        f = _tone(tmp_path / f"src{i}.mp3", fmt="MP3")
        out.append({"id": str(i), "path": str(f), "title": f"שיר {i}", "artist": "ישי ריבו" if i else "",
                    "topic_label": "שבת", "duration": 2.0})
    return out


def test_flat_numbered_in_order_and_tagged(tmp_path):
    dest = tmp_path / "player"
    dest.mkdir()
    plan = export.make_plan(_songs(tmp_path), dest, folder="שבת", layout="flat")
    assert [i.rel for i in plan.items] == ["001 שיר 0.mp3", "002 ישי ריבו - שיר 1.mp3", "003 ישי ריבו - שיר 2.mp3"]
    out = export.run(plan)
    assert out["copied"] == 3 and out["ok"]
    f = dest / "שבת" / "002 ישי ריבו - שיר 1.mp3"
    assert tags.read_tags(f)["artist"] == "ישי ריבו"
    # The second time nothing is copied again.
    again = export.make_plan(_songs(tmp_path), dest, folder="שבת", layout="flat")
    assert again.to_dict()["already"] == 3
    assert export.run(again)["already"] == 3


def test_folders_by_singer(tmp_path):
    dest = tmp_path / "player"
    dest.mkdir()
    plan = export.make_plan(_songs(tmp_path), dest, folder="המנגן", layout="singer")
    assert {str(Path(i.rel).parent) for i in plan.items} == {"זמרים שונים", "ישי ריבו"}


def test_only_what_fits(tmp_path):
    dest = tmp_path / "player"
    dest.mkdir()
    songs = _songs(tmp_path, 5)
    one = Path(songs[0]["path"]).stat().st_size
    plan = export.make_plan(songs, dest, folder="x", limit_bytes=int(one * 2.5))
    assert len(plan.items) == 2 and plan.to_dict()["left_out_count"] == 3


def test_cancel_stops_between_songs(tmp_path):
    import threading

    dest = tmp_path / "player"
    dest.mkdir()
    plan = export.make_plan(_songs(tmp_path), dest, folder="x")
    stop = threading.Event()
    stop.set()
    out = export.run(plan, cancel=stop)
    assert out["cancelled"] and out["copied"] == 0


@pytest.mark.skipif(not HAVE_FFMPEG, reason="no ffmpeg")
def test_other_formats_become_mp3(tmp_path):
    dest = tmp_path / "player"
    dest.mkdir()
    f = _tone(tmp_path / "a.flac", fmt="FLAC")
    songs = [{"id": "a", "path": str(f), "title": "שיר", "artist": "זמר", "duration": 2.0}]
    plan = export.make_plan(songs, dest, folder="x", numbered=False)
    out = export.run(plan, ffmpeg=shutil.which("ffmpeg"))
    assert out["copied"] == 1
    assert (dest / "x" / "זמר - שיר.mp3").is_file()
    assert f.is_file()                                   # the listener's file stays


def test_ringtone_start_is_past_the_opening():
    assert ringtone.suggest_start(240) == 30.0
    assert ringtone.suggest_start(40) == 0.0
    assert ringtone.suggest_start(60) == 24.0


@pytest.mark.skipif(not HAVE_FFMPEG, reason="no ffmpeg")
@pytest.mark.parametrize("fmt", ["mp3", "m4r"])
def test_ringtone_is_cut_and_saved(tmp_path, fmt):
    import mutagen

    src = _tone(tmp_path / "song.wav", seconds=12)
    out = ringtone.make(shutil.which("ffmpeg"), src, tmp_path / "צלצולים", name="זמר - שיר", start=2, length=6,
                        fmt=fmt, duration=12)
    assert out["ok"], out
    p = Path(out["path"])
    assert p.suffix == f".{fmt}" and 5 < mutagen.File(p).info.length < 7
    second = ringtone.make(shutil.which("ffmpeg"), src, tmp_path / "צלצולים", name="זמר - שיר", start=2, length=6,
                           fmt=fmt)
    assert Path(second["path"]).name == f"זמר - שיר (2).{fmt}"


def test_ringtone_without_ffmpeg_says_so(tmp_path):
    out = ringtone.make("", tmp_path / "x.mp3", tmp_path, name="x", start=0)
    assert not out["ok"] and "ffmpeg" in out["message"]


def test_a_list_of_singers_unifies_names(tmp_path):
    from hamenagen.models import Track
    from hamenagen.service import PlayerService

    svc = PlayerService(data_dir=tmp_path / "data")
    svc.index.upsert_many([Track(id="a", path="a.mp3", title="א", artist="Nachman Hadad"),
                           Track(id="b", path="b.mp3", title="ב", artist="נחמן חדד")])
    svc._forget_artists()
    assert svc.artist_name("Nachman Hadad") == "Nachman Hadad"
    lst = tmp_path / "singers.csv"
    lst.write_text("שם,כתיבים\nנחמן חדד,Nachman Hadad,N. Hadad\n", encoding="utf-8")
    out = svc.import_singers(str(lst))
    assert out["ok"] and out["count"] == 1 and out["source"] == "singers.csv"
    assert svc.artist_name("Nachman Hadad") == "נחמן חדד"
    # Kept for the next start; and removed on request.
    again = PlayerService(data_dir=tmp_path / "data")
    assert again.singers_status()["count"] == 1
    again.clear_singers()
    assert again.singers_status()["count"] == 0
