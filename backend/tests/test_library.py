"""The 1.0 library features: tags, favorites, history, paging, scanning."""

import io
import json
import os
import time
from datetime import datetime, timedelta

from hamenagen.index_db import MusicIndex, encode_tags
from hamenagen.models import Track
from hamenagen.rpc import RpcServer
from hamenagen.service import PlayerService

SONG_BYTES = b"\0" * (70 * 1024)  # over the scanner's "not a notification sound" floor


def _track(i, **kw):
    base = dict(id=str(i), path=f"/music/song{i}.mp3", title=f"שיר {i}", filename=f"song{i}.mp3")
    base.update(kw)
    return Track(**base)


def _library(root, names):
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).write_bytes(SONG_BYTES)
    return root


def test_tags_make_a_song_belong_to_two_topics():
    with MusicIndex(":memory:") as idx:
        idx.upsert(_track(1, topic="שבת", tags=encode_tags(["ווקאלי"])))
        idx.upsert(_track(2, topic="ווקאלי"))
        idx.upsert(_track(3, topic="חנוכה"))
        assert {t.id for t in idx.by_topic("ווקאלי")} == {"1", "2"}
        assert {t.id for t in idx.by_topic("שבת")} == {"1"}
        assert idx.topic_counts() == {"שבת": 1, "ווקאלי": 2, "חנוכה": 1}


def test_favorites_history_and_most_played():
    with MusicIndex(":memory:") as idx:
        for i in range(1, 5):
            idx.upsert(_track(i))
        idx.set_favorite("2", True)
        idx.set_favorite("3", True)
        idx.set_favorite("3", False)
        assert idx.favorite_ids() == {"2"}
        assert [t.id for t in idx.favorites()] == ["2"]

        t0 = datetime(2026, 11, 11, 20, 0)
        idx.record_play("1", t0)
        idx.record_play("4", t0 + timedelta(minutes=5))
        idx.record_play("1", t0 + timedelta(minutes=10))
        idx.record_play("1", t0 + timedelta(minutes=15))
        assert [t.id for t in idx.history()] == ["1", "4"]
        assert [t.id for t in idx.most_played()] == ["1", "4"]
        assert idx.play_counts(["1", "4", "2"]) == {"1": 3, "4": 1}


def test_list_tracks_pages_sorts_and_filters():
    with MusicIndex(":memory:") as idx:
        idx.upsert(_track(1, title="בגלל", artist="ב", topic="שבת", duration=200))
        idx.upsert(_track(2, title="אמת", artist="א", topic="חנוכה", duration=100))
        idx.upsert(_track(3, title="גשם", artist="", topic=None, duration=300))
        page = idx.list_tracks(sort="title", limit=2)
        assert page["total"] == 3 and [t.title for t in page["tracks"]] == ["אמת", "בגלל"]
        page = idx.list_tracks(sort="duration", descending=True)
        assert [t.id for t in page["tracks"]] == ["3", "1", "2"]
        assert idx.list_tracks(topic="שבת")["total"] == 1
        assert idx.list_tracks(topic="__none__")["total"] == 1
        assert idx.list_tracks(text="גש")["total"] == 1
        idx.set_favorite("2", True)
        assert [t.id for t in idx.list_tracks(favorites_only=True)["tracks"]] == ["2"]
        assert idx.stats()["tracks"] == 3 and idx.stats()["untagged"] == 1


def test_meta_roundtrip():
    with MusicIndex(":memory:") as idx:
        assert idx.get_meta("last_scan_at") is None
        idx.set_meta("last_scan_at", "2026-11-11T08:00:00")
        assert idx.get_meta("last_scan_at") == "2026-11-11T08:00:00"


def test_rescan_is_incremental(tmp_path):
    music = _library(tmp_path / "music", ["ישי ריבו - מנוחה ושמחה.mp3", "להקה - נרות חנוכה.mp3", "שיר רגיל.mp3"])
    (music / "צליל.mp3").write_bytes(b"x" * 100)  # a notification sound: skipped
    service = PlayerService(data_dir=tmp_path / "data")
    service.settings.use_embeddings = False
    service.classifier.embedding = None

    first = service.rescan([str(music)])
    assert (first["added"], first["updated"], first["removed"], first["total"]) == (3, 0, 0, 3)
    assert service.index.get_meta("last_scan_at")

    again = service.rescan([str(music)])
    assert (again["added"], again["updated"], again["removed"]) == (0, 0, 0)

    changed = music / "שיר רגיל.mp3"
    changed.write_bytes(SONG_BYTES + b"more")
    os.utime(changed, (time.time() + 5, time.time() + 5))
    (music / "להקה - נרות חנוכה.mp3").unlink()
    third = service.rescan([str(music)])
    assert (third["added"], third["updated"], third["removed"], third["total"]) == (0, 1, 1, 2)
    service.close()


def test_requests_over_a_real_library(tmp_path):
    music = _library(tmp_path / "music", [
        "ישי ריבו - מנוחה ושמחה.mp3", "זמירות - יה ריבון.mp3", "להקה - נרות חנוכה.mp3",
        "אברהם פריד - ירושלים של זהב.mp3", "שמוליק סוכות - אמת.mp3",
    ])
    service = PlayerService(data_dir=tmp_path / "data")
    service.settings.use_embeddings = False
    service.classifier.embedding = None
    service.rescan([str(music)])

    shabbat = service.handle_request("שעה של שירי שבת")
    assert shabbat["understood"] == "שעה של שירי שבת"
    assert {t["title"] for t in shabbat["tracks"]} == {"מנוחה ושמחה", "יה ריבון"}

    # "ירושלים של זהב" names a song: the song is found, not the topic.
    song = service.handle_request("ירושלים של זהב")
    assert song["tracks"][0]["title"] == "ירושלים של זהב"
    assert song["understood"].startswith("חיפוש")

    emet = service.handle_request("תשמיע אמת של שמוליק סוכות")
    assert emet["tracks"][0]["artist"] == "שמוליק סוכות"

    missing = service.handle_request("תשמיע שיר שלא קיים בכלל במחשב")
    assert missing["found_local"] is False and missing["note"]

    first_id = shabbat["tracks"][0]["id"]
    service.set_favorite(first_id, True)
    favs = service.handle_request("השירים שאהבתי")
    assert [t["id"] for t in favs["tracks"]] == [first_id] and favs["tracks"][0]["favorite"] is True

    assert service.handle_request("מה ששמעתי לאחרונה")["found_local"] is False
    service.record_play(first_id)
    assert [t["id"] for t in service.handle_request("מה ששמעתי לאחרונה")["tracks"]] == [first_id]

    overview = service.library_overview()
    assert overview["stats"]["tracks"] == 5 and overview["stats"]["favorites"] == 1
    counts = {t["key"]: t["count"] for t in overview["topics"]}
    assert counts["שבת"] == 2 and counts["חנוכה"] == 1

    tile = service.playlist("play_topic", topic="חנוכה")
    assert tile["understood"] == "שירי חנוכה" and tile["count"] == 1
    service.close()


def test_rpc_loop_answers_and_emits(tmp_path):
    music = _library(tmp_path / "music", ["ישי ריבו - מנוחה ושמחה.mp3"])
    service = PlayerService(data_dir=tmp_path / "data")
    service.settings.use_embeddings = False
    service.classifier.embedding = None
    server = RpcServer(service)
    requests = [
        {"id": 1, "method": "ping"},
        {"id": 2, "method": "rescan", "params": {"roots": [str(music)]}},
        {"id": 3, "method": "today"},
        {"id": 4, "method": "no_such_method"},
        {"id": 5, "method": "app_info"},
    ]
    stdin = io.StringIO("".join(json.dumps(r) + "\n" for r in requests))
    stdout = io.StringIO()
    server.serve(stdin=stdin, stdout=stdout, wait=True)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]["event"] == "ready"
    by_id = {m["id"]: m for m in lines if "id" in m}
    assert by_id[1]["result"] == {"pong": True}
    assert by_id[2]["result"]["added"] == 1
    assert "hebrew" in by_id[3]["result"]
    assert by_id[4]["ok"] is False
    assert by_id[5]["result"]["version"]
    service.close()


def test_folder_names_hint_the_topic(tmp_path):
    music = tmp_path / "music"
    _library(music / "חתונות", ["תזמורת - ריקוד הפתיחה.mp3"])
    _library(music / "שבת" / "זמירות", ["מקהלה - ניגון ערב.mp3"])
    _library(music, ["אמן - שיר רגיל.mp3"])
    service = PlayerService(data_dir=tmp_path / "data")
    service.settings.use_embeddings = False
    service.classifier.embedding = None
    service.rescan([str(music)])
    topics = {t.title: t.topic for t in service.index.all_tracks()}
    assert topics["ריקוד הפתיחה"] == "חתונה"
    assert topics["ניגון ערב"] == "שבת"
    assert topics["שיר רגיל"] is None
    service.close()


def test_settings_from_0_1_move_to_the_new_model(tmp_path):
    from hamenagen.settings import DEFAULT_MODEL, Settings

    old = tmp_path / "settings.json"
    old.write_text(json.dumps({
        "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "embedding_threshold": 0.5,
    }), encoding="utf-8")
    s = Settings.load(old)
    assert s.embedding_model == DEFAULT_MODEL
    assert s.embedding_threshold == 0.91
