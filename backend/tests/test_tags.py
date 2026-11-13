"""Writing a song's details into the file (tags.py) and from the library."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from hamenagen import tags

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")
pytest.importorskip("mutagen")


def _tone(path, fmt=None):
    t = np.arange(8000) / 8000
    sf.write(path, 0.2 * np.sin(2 * np.pi * 440 * t), 8000, format=fmt)
    return path


@pytest.mark.parametrize("ext,fmt", [(".flac", "FLAC"), (".ogg", "OGG"), (".mp3", "MP3")])
def test_details_go_into_the_file(tmp_path, ext, fmt):
    f = _tone(tmp_path / f"song{ext}", fmt)
    ok, why = tags.write_tags(f, title="ירושלים של זהב", artist="ישי ריבו", album="שירי ירושלים")
    assert ok, why
    assert tags.read_tags(f) == {"title": "ירושלים של זהב", "artist": "ישי ריבו", "album": "שירי ירושלים"}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg")
def test_m4a_with_a_cover(tmp_path):
    wav = _tone(tmp_path / "a.wav")
    m4a = tmp_path / "a.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", str(m4a)], check=True)
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 3000
    ok, why = tags.write_tags(m4a, title="שיר", artist="זמר", cover=jpeg)
    assert ok, why
    from mutagen.mp4 import MP4
    assert MP4(m4a).tags["covr"] and tags.read_tags(m4a)["artist"] == "זמר"


def test_other_formats_are_left_alone(tmp_path):
    f = _tone(tmp_path / "a.wav")
    assert tags.write_tags(f, title="x") == (False, "format")


def test_the_library_writes_the_name_it_shows(tmp_path):
    from hamenagen.models import Track
    from hamenagen.service import PlayerService

    a = _tone(tmp_path / "a.mp3", "MP3")
    b = _tone(tmp_path / "b.mp3", "MP3")
    svc = PlayerService(data_dir=tmp_path / "data")
    svc.index.upsert_many([Track(id="a", path=str(a), title="שיר אחד", artist="ישי ריבו"),
                           Track(id="b", path=str(b), title="שיר שני", artist="Ishay Ribo")])
    svc._forget_artists()
    out = svc.write_track_tags(["a", "b"])
    assert out["written"] == 2 and out["ok"]
    assert tags.read_tags(b)["artist"] == "ישי ריבו"          # the unified name
    assert svc.write_track_tags(["a", "b"])["unchanged"] == 2  # nothing to change the second time
    svc.close()
