"""רדיו המנגן (station.py): by the time of day and the calendar, or after a song."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest
from hamenagen import station as st


def _songs():
    return [st.Candidate(id=f"s{i}", artist=f"a{i % 4}", energy=i / 19, tempo=70 + 5 * i) for i in range(20)]


def test_the_time_of_day():
    assert [st.daypart(datetime(2026, 1, 1, h)).key for h in (0, 4, 5, 9, 13, 17, 20, 23)] == [
        "night", "night", "morning", "forenoon", "afternoon", "dusk", "evening", "night"]


def test_night_is_soft_and_the_forenoon_lively():
    rng = random.Random(1)
    night = st.pick(_songs(), 6, mood=st.Mood(st.daypart(datetime(2026, 1, 1, 0))), rng=rng)
    day = st.pick(_songs(), 6, mood=st.Mood(st.daypart(datetime(2026, 1, 1, 10))), rng=rng)
    avg = lambda xs: sum(c.energy for c in xs) / len(xs)
    assert avg(night) < 0.4 < avg(day)


def test_no_repeats_no_recent_songs_and_singers_spaced():
    songs = _songs()
    songs[5].hours_since_played = 1.0          # heard an hour ago
    mood = st.Mood(st.daypart(datetime(2026, 1, 1, 14)))
    first = st.pick(songs, 8, mood=mood, rng=random.Random(2))
    more = st.pick(songs, 8, mood=mood, history=[c.id for c in first], rng=random.Random(3))
    ids = [c.id for c in first + more]
    assert len(ids) == len(set(ids)) and "s5" not in ids
    artists = [c.artist for c in first]
    assert all(a != b for a, b in zip(artists, artists[1:]))


def test_the_calendar_comes_first_and_holiday_songs_wait_for_their_days():
    songs = _songs()
    songs[0].topic, songs[1].topic, songs[2].topic = "שבת", "חנוכה", "פסח"
    mood = st.Mood(st.daypart(datetime(2026, 1, 1, 14)), topic="חנוכה",
                   out_of_season=frozenset({"פסח", "פורים"}))
    ids = [c.id for c in st.pick(songs, 19, mood=mood, rng=random.Random(4))]
    assert "s2" not in ids and ids.index("s1") < 4


def test_vocal_only_days():
    songs = _songs()
    songs[3].vocal = songs[7].vocal = True
    mood = st.Mood(st.daypart(datetime(2026, 1, 1, 14)), vocal_only=True)
    assert {c.id for c in st.pick(songs, 10, mood=mood)} == {"s3", "s7"}


def test_from_a_song_the_same_singer_and_tempo_lead():
    songs = _songs()
    seed = songs[10]
    picked = st.pick(songs, 4, seed=seed, rng=random.Random(5))
    assert seed.id not in [c.id for c in picked]
    assert sum(1 for c in picked if abs(c.energy - seed.energy) < 0.25) >= 3


def test_the_service_station(tmp_path):
    pytest.importorskip("numpy")
    from hamenagen.models import Track
    from hamenagen.service import PlayerService

    svc = PlayerService(data_dir=tmp_path / "data")
    svc.index.upsert_many([Track(id=f"t{i}", path=f"/m/{i}.mp3", title=f"שיר {i}", artist=f"זמר {i % 3}",
                                 duration=200.0) for i in range(12)]
                          + [Track(id="talk", path="/m/talk.mp3", title="שיעור", duration=1800.0)])
    svc._update_kinds()
    out = svc.station()
    assert out["ok"] and out["mode"] == "time" and out["title"].startswith("רדיו המנגן")
    ids = [t["id"] for t in out["tracks"]]
    assert "talk" not in ids and len(ids) == svc.STATION_BATCH
    more = svc.station(history=ids)
    assert not set(ids) & {t["id"] for t in more["tracks"]}
    svc.index.record_play("t0", datetime.now() - timedelta(minutes=10))
    assert "t0" not in [t["id"] for t in svc.station(count=12)["tracks"]]
    song = svc.station(seed="t3")
    assert song["tracks"][0]["id"] == "t3" and song["mode"] == "song"
    assert svc.station(seed="nope")["ok"] is False
    svc.close()


def test_a_mood_request_and_only_a_mood_request():
    assert st.mood_request("משהו רגוע").key == "calm"
    assert st.mood_request("תשמיע לי שירים מרגשים בבקשה").key == "moving"
    assert st.mood_request("שירי ילדים").key == "children"
    assert st.mood_request("ירושלים של זהב") is None
    assert st.mood_request("דוד המלך רגוע") is None      # a song name, not a mood


def test_the_service_plays_a_calm_hour(tmp_path):
    pytest.importorskip("numpy")
    from hamenagen.models import Track
    from hamenagen.service import PlayerService

    svc = PlayerService(data_dir=tmp_path / "data")
    svc.index.upsert_many([Track(id=f"t{i}", path=f"/m/{i}.mp3", title=f"שיר {i}", artist=f"זמר {i}",
                                 duration=240.0) for i in range(10)])
    for i in range(10):
        svc.index.save_analysis(f"t{i}", {"model": "test", "verdict": "instruments", "energy": i / 9, "tempo": 70 + 8 * i})
    out = svc.handle_request("שעה של שירים שקטים")
    assert "רגועים" in out["understood"]
    energies = [int(t["id"][1:]) for t in out["tracks"]]
    assert sum(energies) / len(energies) < 4.5
    svc.close()
