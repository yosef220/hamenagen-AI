"""1.6: clean names for songs from the web, approved, and undone."""

import pytest

from hamenagen.models import Track
from hamenagen.name_fix import clean_title, suggest
from hamenagen.service import PlayerService


@pytest.mark.parametrize("title,artist,new_title,new_artist,sure", [
    ("ישי ריבו - מנוחה ושמחה (Official Video) | Ishay Ribo", "", "מנוחה ושמחה", "ישי ריבו", True),
    ("מנוחה ושמחה [HD]", "ישי ריבו", "מנוחה ושמחה", "ישי ריבו", True),
    ("ישי ריבו - מנוחה ושמחה", "ישי ריבו", "מנוחה ושמחה", "ישי ריבו", True),
    ("מוטי שטיינמץ - הקליפ הרשמי - יחד", "Jewish Music Channel", "יחד", "מוטי שטיינמץ", False),
    ("שיר www.example.co.il", "זמר", "שיר", "זמר", True),
    ("עוצו עצה (Prod. By Someone)", "זמר", "עוצו עצה", "זמר", True),
    ("מנוחה ושמחה", "Ishay Ribo - Topic", "מנוחה ושמחה", "Ishay Ribo", True),
])
def test_suggestions(title, artist, new_title, new_artist, sure):
    fix = suggest(title, artist)
    assert (fix.title, fix.artist, fix.sure) == (new_title, new_artist, sure)
    assert fix.why


@pytest.mark.parametrize("title,artist", [
    ("אבינו מלכנו - לייב", "אברהם פריד"),      # a live performance stays marked
    ("Live in Caesarea (Live)", "x"),
    ("100 אחוז", "x"),
    ("קליפ", "x"),                                  # a song really named so
    ("מנוחה ושמחה", "ישי ריבו"),
])
def test_clean_names_are_left_alone(title, artist):
    assert suggest(title, artist) is None


def test_the_english_half_goes_only_beside_hebrew():
    assert clean_title("Shalom Aleichem | Live")[0] == "Shalom Aleichem | Live"


def test_approve_then_undo(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    song = music / "x.mp3"
    song.write_bytes(b"\0" * 1000)
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.index.upsert(Track(id="a", path=str(song), title="ישי ריבו - מנוחה ושמחה (Official Video)",
                                   filename="x.mp3"))
        service.index.upsert(Track(id="b", path=str(music / "y.mp3"), title="שיר נקי", artist="זמר"))
        got = service.name_suggestions()["suggestions"]
        assert [(s["id"], s["new_title"], s["new_artist"]) for s in got] == [("a", "מנוחה ושמחה", "ישי ריבו")]
        r = service.apply_name_fixes([{"id": "a", "title": "מנוחה ושמחה", "artist": "ישי ריבו"}])
        assert r["applied"] == 1
        t = service.index.get("a")
        assert (t.title, t.artist) == ("מנוחה ושמחה", "ישי ריבו")
        assert t.topic == "שבת"          # a known song, now that its name is clean
        assert service.name_suggestions() == {"suggestions": [], "applied": 1}
        # Undone: back to what the file says (here, its name: no tags).
        assert service.undo_name_fixes()["restored"] == 1
        assert service.index.get("a").title == "x"
        assert service.index.details() == {}
    finally:
        service.close()
