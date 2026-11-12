"""Sets for an occasion: understanding the request, the order, and YouTube
in the listener's style when the computer has too few songs."""

from pathlib import Path

from hamenagen import sets as sets_mod
from hamenagen.intent import Action, parse
from hamenagen.models import Track


def test_requests_for_a_set():
    cases = {
        "תפעיל לי סט שירים לברית": ("brit", None),
        "שירים לברית מילה": ("brit", None),
        "סט לבר מצווה": ("bar_mitzvah", None),
        "מוזיקה לריקודים": ("simcha", None),
        "משהו קצבי": ("simcha", None),
        "סט לחתונה": ("wedding", None),
        "סט שירי שבת": (None, "שבת"),
    }
    for text, (event, topic) in cases.items():
        i = parse(text)
        assert i.action == Action.SET, text
        assert i.params.get("event") == event and i.topic == topic, (text, i.params, i.topic)
    # Not sets: a song whose name has a celebration word, and the wedding topic.
    assert parse("ברית עולם").action == Action.SEARCH_SONG
    assert parse("רוקדים במעגל").action == Action.SEARCH_SONG
    assert parse("שירים לחתונה").action == Action.PLAY_TOPIC
    assert parse("שעה של סט לבר מצווה").minutes == 60


def test_the_set_warms_up_peaks_and_eases_off():
    songs = [sets_mod.SetSong(track=i, tempo=90 + 5 * i, energy=e)
             for i, e in enumerate([0.2, 0.9, 0.4, 0.7, 0.5, 0.8, 0.3, 0.6, 0.95, 0.45])]
    order = [s.energy for s in sets_mod.arrange(songs, seed=1)]
    peak = order.index(max(order))
    assert 0.6 <= peak / (len(order) - 1) <= 0.95          # the peak comes late
    assert order[0] <= 0.3                                  # a gentle start
    assert sum(order[:3]) < sum(order[5:8])                 # it builds
    assert order[-1] < max(order)                           # and eases off


def test_style_queries_use_the_listeners_singers():
    artists = sets_mod.top_artists([("אברהם פריד", 5), ("ישי ריבו", 9), ("", 30), ("שונים", 40),
                                    ("אברהם  פריד", 2)])
    assert artists == ["ישי ריבו", "אברהם פריד"]
    q = sets_mod.online_queries(sets_mod.EVENTS["brit"], artists)
    assert q[0] == "שירים לברית מילה" and "ישי ריבו שמחה" in q


def song(tid, title, artist="", topic=None, duration=200.0):
    return Track(id=tid, path=f"/m/{tid}.mp3", title=title, artist=artist, duration=duration, topic=topic,
                 filename=f"{tid}.mp3", size=4_000_000 + hash(tid) % 1000)


def test_a_set_for_a_brit_from_the_library(tmp_path):
    from hamenagen.service import PlayerService

    svc = PlayerService(tmp_path)
    svc.index.upsert_many([
        song("b1", "סימן טוב ומזל טוב", "אברהם פריד", "חתונה"),
        song("b2", "אליהו הנביא", "מקהלה"),
        song("w1", "קול ששון", "להקה", "חתונה"),
        song("w2", "מזל טוב", "להקה", "חתונה"),
        song("x1", "ריקוד", "תזמורת"),
        song("q1", "שיר שקט", "זמר"),
        song("k1", "כל נדרי", "חזן", "יום כיפור"),
        song("h1", "סביבון", "ילדים", "חנוכה"),
    ])
    energy = {"b1": 0.7, "b2": 0.5, "w1": 0.8, "w2": 0.6, "x1": 0.9, "q1": 0.2, "k1": 0.9, "h1": 0.95}
    for tid, e in energy.items():
        svc.index.save_analysis(tid, {"tempo": 120.0, "energy": e, "mtime": None, "size": None})
    res = svc.handle_request("תפעיל לי סט שירים לברית")
    ids = [t["id"] for t in res["tracks"]]
    assert res["understood"] == "סט לברית"
    assert {"b1", "b2", "w1", "w2", "x1"} <= set(ids)       # the brit's own, the celebration topic, dancing
    assert "q1" not in ids and "k1" not in ids              # not a quiet song, never Yom Kippur
    assert "h1" not in ids                                  # a Chanukah song is for Chanukah
    assert res["set"]["crossfade"] >= 6
    # Seven songs is too few for a set: YouTube is offered, in the listener's style.
    svc.index.record_play("b1")
    assert res["online"] is not None
    online = svc.handle_request("סט לבר מצווה")["online"]
    assert online["label"] == "בר מצווה" and online["queries"][0] == "שירים לבר מצווה"


def test_youtube_for_a_set_and_listening_without_saving(tmp_path, monkeypatch):
    from hamenagen.demo_online import DemoSource
    from hamenagen.fetcher import OnlineFetcher
    from hamenagen.service import PlayerService

    svc = PlayerService(tmp_path)
    svc.fetcher = OnlineFetcher(DemoSource())
    svc.index.upsert(song("e1", "המלאך", "אלי הרצליך"))
    out = svc.online_set("brit", None)
    assert out["ok"] and out["results"] and "אלי הרצליך" in out["artists"]
    assert all(60 <= (r["duration"] or 60) <= 75 * 60 for r in out["results"])
    first = out["results"][0]
    from hamenagen.fetcher import SearchResult
    ready = svc.listen_prepare(SearchResult(**{k: first[k] for k in SearchResult.__dataclass_fields__}))
    assert ready["ok"] and Path(ready["path"]).exists()
    assert Path(ready["path"]).parent == svc.listen_dir
    assert not list(svc.downloads_dir.glob("*")) if svc.downloads_dir.exists() else True
    # The cache stays small: the oldest files go first.
    monkeypatch.setattr(svc, "LISTEN_CACHE_MB", 0)
    (svc.listen_dir / "old.m4a").write_bytes(b"x" * 1000)
    svc._trim_listen_cache(keep=ready["path"])
    assert Path(ready["path"]).exists() and not (svc.listen_dir / "old.m4a").exists()
