"""1.6: the words of a song — from its tags or a file beside it — kept in the
index, found by a line the listener remembers, and read for its occasion."""

import pytest

from hamenagen.classifier import HybridClassifier
from hamenagen.index_db import MusicIndex
from hamenagen.models import Track
from hamenagen.scanner import plain_lyrics, read_sidecar_lyrics, scan_file, timed_lyrics
from hamenagen.service import PlayerService

LRC = """[ar:ישי ריבו]
[ti:שיר]
[00:01.00]שורה ראשונה של השיר
[00:05.50]והנה באה השורה השנייה
[00:09.25][00:30.00]פזמון שחוזר
"""


def _mp3(path, frames=60):
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * frames)
    return path


def test_lrc_times_are_read_and_stripped():
    assert plain_lyrics(LRC).splitlines() == ["שורה ראשונה של השיר", "והנה באה השורה השנייה", "פזמון שחוזר"]
    rows = timed_lyrics(LRC)
    assert [r["t"] for r in rows] == [1.0, 5.5, 9.25, 30.0]
    assert rows[-1]["text"] == "פזמון שחוזר"
    assert timed_lyrics("שורה\nועוד שורה") == []


def test_lrc_offset_moves_every_line():
    rows = timed_lyrics("[offset:+500]\n[00:02.00]א\n[00:03.00]ב\n[00:04.00]ג")
    assert [r["t"] for r in rows] == [1.5, 2.5, 3.5]


def test_a_sidecar_in_the_old_hebrew_code_page_is_read(tmp_path):
    song = tmp_path / "שיר.mp3"
    song.write_bytes(b"\0" * 10)
    (tmp_path / "שיר.txt").write_bytes("לכה דודי לקראת כלה".encode("cp1255"))
    assert read_sidecar_lyrics(song) == "לכה דודי לקראת כלה"


def test_words_in_the_tags_are_read(tmp_path):
    mutagen = pytest.importorskip("mutagen")  # noqa: F841
    from mutagen.id3 import ID3, TIT2, USLT

    song = _mp3(tmp_path / "x.mp3")
    tags = ID3()
    tags.add(TIT2(encoding=3, text="שיר"))
    tags.add(USLT(encoding=3, lang="heb", desc="", text="אני מאמין\nבאמונה שלמה"))
    tags.save(song)
    track = scan_file(song)
    assert track.lyrics.splitlines() == ["אני מאמין", "באמונה שלמה"]
    assert "lyrics" not in track.to_dict()


def test_the_index_finds_a_song_by_a_line():
    with MusicIndex(":memory:") as idx:
        idx.upsert(Track(id="1", path="/m/a.mp3", title="א"))
        idx.upsert(Track(id="2", path="/m/b.mp3", title="ב"))
        idx.set_lyrics("1", "שורה ראשונה\nוְהַשּׁוּרָה השנייה של השיר", "tag")
        idx.set_lyrics("2", "משהו אחר לגמרי", "file")
        found = idx.search_lyrics(["השורה", "השנייה"])
        assert [t.id for t, _ in found] == ["1"]
        assert found[0][1] == "וְהַשּׁוּרָה השנייה של השיר"
        assert idx.lyrics_count() == 2
        # The library's search box: three words or more may be a line.
        assert [t.id for t in idx.list_tracks(text="השורה השנייה של")["tracks"]] == ["1"]
        idx.set_lyrics("2", "", "tag")
        assert idx.get_lyrics("2") is None


def test_an_occasion_must_come_back_in_the_words():
    clf = HybridClassifier()
    # Said once, in passing, deep in the song: not enough.
    once = "\n".join(["שורה"] * 6 + ["ונלך כולנו לשבת יחד"] + ["עוד שורה"] * 4)
    assert clf.classify(title="שיר בלי רמז", lyrics=once).topic is None
    # The chorus comes back to it: the song is about it.
    chorus = "\n".join(["אור של חנוכה בבית", "שורה אחרת", "אור של חנוכה בבית"])
    c = clf.classify(title="שיר בלי רמז", lyrics=chorus)
    assert (c.topic, c.source) == ("חנוכה", "lyrics")
    assert "חנוכה" in c.note
    # Its name still comes first.
    assert clf.classify(title="נרות חנוכה", lyrics="שבת שלום\nשבת שלום\nשבת").topic == "חנוכה"


def test_a_scan_keeps_the_words_and_a_request_finds_the_song_by_them(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    (music / "זמר - שיר בלי שם ידוע.mp3").write_bytes(b"\0" * (70 * 1024))
    (music / "זמר - שיר בלי שם ידוע.lrc").write_text(LRC, encoding="utf-8")
    (music / "שיר אחר.mp3").write_bytes(b"\0" * (70 * 1024))
    service = PlayerService(data_dir=tmp_path / "data")
    service.settings.scan_roots = [str(music)]
    try:
        service.rescan(index=service.index)
        res = service.handle_request("והנה באה השורה")
        assert [t["title"] for t in res["tracks"]] == ["שיר בלי שם ידוע"]
        assert "מילות השיר" in res["note"]
        words = service.track_lyrics(res["tracks"][0]["id"])
        assert words["source"] == "file" and words["lyrics"].startswith("שורה ראשונה")
        assert len(words["lines"]) == 4
    finally:
        service.close()
