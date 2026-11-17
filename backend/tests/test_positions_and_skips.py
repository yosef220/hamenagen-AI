"""1.6: a long recording goes on from where it stopped, a song paused in the
middle offers to return there, and early skips (not quick browsing) lower a
song in the radio."""

from datetime import datetime, timedelta

from hamenagen import station as st
from hamenagen.index_db import MusicIndex
from hamenagen.models import Track
from hamenagen.service import PlayerService


def _service(tmp_path, *tracks):
    service = PlayerService(data_dir=tmp_path / "data")
    for t in tracks:
        service.index.upsert(t)
    return service


def test_a_long_recording_keeps_its_place_wherever_it_stopped(tmp_path):
    shiur = Track(id="s", path="/m/shiur.mp3", title="שיעור בפרשה", duration=55 * 60, kind="speech")
    service = _service(tmp_path, shiur)
    try:
        assert service.save_position("s", 1234.5)["kept"]
        payload = service._tracks_payload([service.index.get("s")])[0]
        assert payload["long"] and payload["resume"] == 1234.5
        assert [t["id"] for t in service.library_overview()["started"]] == ["s"]
        # Near its end it is done, and nothing is kept.
        assert not service.save_position("s", 55 * 60 - 20)["kept"]
        assert service.index.get_position("s") is None
        assert service.library_overview()["started"] == []
    finally:
        service.close()


def test_a_song_is_kept_only_when_paused_in_the_middle(tmp_path):
    song = Track(id="a", path="/m/a.mp3", title="שיר", duration=240)
    service = _service(tmp_path, song)
    try:
        assert not service.save_position("a", 100, paused=False)["kept"]   # skipped: not wanted
        assert not service.save_position("a", 10, paused=True)["kept"]     # hardly begun
        assert not service.save_position("a", 230, paused=True)["kept"]    # all but over
        assert service.save_position("a", 100, paused=True)["kept"]
        assert service.index.get_position("a")["seconds"] == 100
        # A song is not a recording to go on with from the home page.
        assert service.library_overview()["started"] == []
    finally:
        service.close()


def test_skips_while_browsing_do_not_count():
    with MusicIndex(":memory:") as idx:
        idx.upsert(Track(id="1", path="/m/1.mp3"))
        idx.record_skip("1", 8.0)
        idx.record_skip("1", 6.0, burst=True)
        idx.record_skip("1", 12.0, when=datetime.now() - timedelta(days=400))
        assert idx.skip_counts() == {"1": 2}
        recent = (datetime.now() - timedelta(days=180)).isoformat(timespec="seconds")
        assert idx.skip_counts(since=recent) == {"1": 1}


def test_a_skip_of_a_moment_is_not_recorded(tmp_path):
    service = _service(tmp_path, Track(id="a", path="/m/a.mp3"))
    try:
        assert not service.record_skip("a", 1.5)["ok"]
        assert service.record_skip("a", 9.0)["ok"]
        assert service.index.skip_counts() == {"a": 1}
    finally:
        service.close()


def test_a_song_often_skipped_falls_in_the_radio():
    kept = st.Candidate(id="k", plays=4)
    skipped = st.Candidate(id="s", plays=4, skips=6)
    once = st.Candidate(id="o", plays=4, skips=1)
    assert st._taste(skipped) < st._taste(kept)
    assert st._taste(once) == st._taste(kept)
