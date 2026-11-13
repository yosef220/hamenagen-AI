"""Songs that live only in the cloud (OneDrive, Dropbox…) are not downloaded by the scan."""

from __future__ import annotations

import os
import time

import pytest

from hamenagen import cloudfiles, scanner
from hamenagen.service import PlayerService

pytest.importorskip("mutagen")
np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")


class _CloudStat:
    """os.stat_result of a file whose contents are still on the server."""

    def __init__(self, st):
        self._st = st
        self.st_file_attributes = cloudfiles.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

    def __getattr__(self, name):
        return getattr(self._st, name)


def _song(path, title):
    t = np.arange(44100 * 25) / 44100            # long and big enough to count as a song
    sf.write(path, 0.2 * np.sin(2 * np.pi * 440 * t), 44100, format="MP3")
    from hamenagen import tags
    tags.write_tags(path, title=title, artist="זמר מהתגית")
    return path


def test_attributes():
    class St:
        st_file_attributes = cloudfiles.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | 0x20
    assert cloudfiles.is_cloud_only(St())
    St.st_file_attributes = 0x20                       # an ordinary file
    assert not cloudfiles.is_cloud_only(St())
    assert not cloudfiles.is_cloud_only(os.stat(__file__))   # no attributes here
    assert cloudfiles.provider(r"C:\Users\x\OneDrive\Music\a.mp3") == "OneDrive"
    assert cloudfiles.provider("/home/x/Dropbox (Personal)/a.mp3") == "Dropbox"


def test_the_scan_takes_cloud_files_by_name(tmp_path, monkeypatch):
    music = tmp_path / "OneDrive" / "Music"
    music.mkdir(parents=True)
    cloud = _song(music / "אברהם פריד - ידיד נפש.mp3", "שם מהתגית")
    local = _song(music / "local.mp3", "שיר מקומי")
    real_iter = scanner.iter_media_files
    on_server = {str(cloud)}

    def fake_iter(roots, **kw):
        for p, st in real_iter(roots, **kw):
            yield p, (_CloudStat(st) if str(p) in on_server else st)

    import hamenagen.service as service_mod
    monkeypatch.setattr(service_mod, "iter_media_files", fake_iter)
    read = []
    real_read = scanner._read_tags
    monkeypatch.setattr(scanner, "_read_tags", lambda p: (read.append(str(p)), real_read(p))[1])

    svc = PlayerService(data_dir=tmp_path / "data")
    out = svc.rescan([str(music)])
    assert out["cloud"] == 1
    assert str(cloud) not in read and str(local) in read            # never opened
    t = svc.index.get(scanner.track_id_for(cloud))
    assert (t.title, t.artist, t.mtime) == ("ידיד נפש", "אברהם פריד", None)   # from its name
    assert all(x.id != t.id for x, _ in svc._needs_listening(svc.index))      # not listened to

    # Played once, it is on the computer: the next scan reads it in full.
    on_server.clear()
    svc.rescan([str(music)])
    t = svc.index.get(scanner.track_id_for(cloud))
    assert t.title == "שם מהתגית" and t.mtime is not None


def test_reading_them_anyway(tmp_path, monkeypatch):
    music = tmp_path / "m"
    music.mkdir()
    cloud = _song(music / "a.mp3", "מהתגית")
    real_iter = scanner.iter_media_files
    import hamenagen.service as service_mod
    monkeypatch.setattr(service_mod, "iter_media_files",
                        lambda roots, **kw: ((p, _CloudStat(st)) for p, st in real_iter(roots, **kw)))
    svc = PlayerService(data_dir=tmp_path / "data")
    svc.settings.cloud_files = "read"
    svc.rescan([str(music)])
    assert svc.index.get(scanner.track_id_for(cloud)).title == "מהתגית"


def test_a_file_that_hangs_does_not_stop_the_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_read_tags", lambda p: time.sleep(5) or {"title": "x"})
    started = time.monotonic()
    assert scanner._read_tags_limited(tmp_path / "a.mp3", timeout=0.2) == {}
    assert time.monotonic() - started < 2


def test_models_are_let_go_when_idle(tmp_path):
    svc = PlayerService(data_dir=tmp_path / "data")
    b = svc.classifier.embedding

    class Fake:
        pass
    b._session, b._matrix = Fake(), object()
    b.last_used = time.monotonic()
    assert not svc.release_idle_models()                 # just used
    b.last_used -= svc.MODEL_IDLE + 1
    assert svc.release_idle_models() and b._session is None
    assert b._matrix is not None                          # the topics' vectors stay
    svc.voice._sessions, svc.voice.last_used = {"x": 1}, time.monotonic() - svc.VOICE_IDLE - 1
    assert svc.release_idle_models() and svc.voice._sessions is None
