"""One singer, one name (artists.py)."""

from __future__ import annotations

from hamenagen import artists as ar
from hamenagen.models import Track


def test_sure_spellings_unify_by_themselves():
    mapping, groups = ar.build({"ישי ריבו": 10, "Ishay Ribo": 3, "ישי ריבו.": 1, "ISHAY RIBO": 1})
    assert mapping == {"Ishay Ribo": "ישי ריבו", "ישי ריבו.": "ישי ריבו", "ISHAY RIBO": "ישי ריבו"}
    assert len(groups) == 1 and groups[0].sure and groups[0].applied and groups[0].known


def test_one_spelling_stays_as_it_is():
    mapping, groups = ar.build({"Shwekey": 5, "חיים": 2})
    assert mapping == {} and groups == []


def test_vowel_letters_are_only_suggested_until_the_listener_agrees():
    counts = {"מוטי שטיינמץ": 4, "מוטי שטינמץ": 2, "Yossi Green": 2, "Yosi Green": 1}
    mapping, groups = ar.build(counts)
    assert mapping == {} and {g.applied for g in groups} == {False}
    choices = {g.key: {"merge": True} for g in groups}
    mapping, groups = ar.build(counts, choices)
    assert mapping["מוטי שטינמץ"] == "מוטי שטיינמץ" and mapping["Yosi Green"] == mapping["Yossi Green"] == "יוסי גרין"


def test_short_names_never_pair():
    _, groups = ar.build({"דוד": 3, "דד": 1, "אבי": 2, "אב": 1})
    assert groups == []


def test_the_listener_can_rename_or_keep_apart():
    counts = {"ישי ריבו": 10, "Ishay Ribo": 3}
    key = ar.build(counts)[1][0].key
    mapping, _ = ar.build(counts, {key: {"name": "Ishay Ribo"}})
    assert mapping == {"ישי ריבו": "Ishay Ribo"}
    mapping, groups = ar.build(counts, {key: {"apart": True}})
    assert mapping == {} and not groups[0].applied


def test_a_search_finds_every_spelling():
    mapping, _ = ar.build({"ישי ריבו": 10, "Ishay Ribo": 3})
    assert ar.expand_query("Ishay Ribo שבת", mapping, {"ישי ריבו"}) == "ישי ריבו שבת"
    # Files only in English: a Hebrew search still finds them.
    assert ar.expand_query("יעקב שוואקי", {}, {"Shwekey"}) == "shwekey"
    assert ar.expand_query("שירי שבת", {}, {"Shwekey"}) == "שירי שבת"


def test_the_service_shows_one_name_and_searches_all(tmp_path):
    from hamenagen.service import PlayerService

    svc = PlayerService(data_dir=tmp_path / "data")
    svc.index.upsert_many([
        Track(id="a", path="/m/a.mp3", title="שיר אחד", artist="ישי ריבו"),
        Track(id="b", path="/m/b.mp3", title="שיר שני", artist="Ishay Ribo"),
        Track(id="c", path="/m/c.mp3", title="שיר שלישי", artist="מוטי שטיינמץ"),
        Track(id="d", path="/m/d.mp3", title="שיר רביעי", artist="מוטי שטינמץ"),
    ])
    svc._forget_artists()
    assert {t["artist"] for t in svc.list_tracks()["tracks"] if t["id"] in "ab"} == {"ישי ריבו"}
    assert {t["id"] for t in svc.list_tracks(text="Ishay Ribo")["tracks"]} == {"a", "b"}
    assert {t["id"] for t in svc.list_tracks(text="ישי ריבו")["tracks"]} == {"a", "b"}
    groups = svc.artist_groups()
    assert groups["waiting"] == 1
    waiting = next(g for g in groups["groups"] if not g["applied"])
    svc.set_artist_choice(waiting["key"], merge=True)
    assert {t["artist"] for t in svc.list_tracks()["tracks"] if t["id"] in "cd"} == {"מוטי שטיינמץ"}
    found = svc.handle_request("Ishay Ribo")
    assert {t["id"] for t in found["tracks"]} == {"a", "b"}
    svc.close()
