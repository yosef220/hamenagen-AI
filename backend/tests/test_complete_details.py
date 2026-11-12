"""Details and covers for the whole library: filled in only for a sure match."""

from hamenagen import metadata
from hamenagen.metadata import Candidate, sure_match
from hamenagen.models import Track


def test_a_sure_match_needs_name_singer_and_length():
    c = Candidate(title="מנוחה ושמחה", artist="אברהם פריד", duration=214.0)
    assert sure_match(c, "מנוחה ושמחה", "אברהם פריד", 215.5)
    assert sure_match(c, "מנוחה ושמחה", "", 212.0)                 # no singer in the file: name + length
    assert not sure_match(c, "מנוחה ושמחה", "אברהם פריד", 230.0)   # another recording
    assert not sure_match(c, "מנוחה", "אברהם פריד", 214.0)          # another name
    assert not sure_match(c, "מנוחה ושמחה", "מקהלת שירת הים", 214.0)
    assert not sure_match(c, "מנוחה ושמחה", "Avraham Fried", 214.0)  # cannot compare the scripts
    assert not sure_match(c, "מנוחה ושמחה", "אברהם פריד", None)


def fake_itunes(url, params):
    if params["term"].endswith("מנוחה ושמחה") or params["term"] == "מנוחה ושמחה":
        return {"results": [{"kind": "song", "trackName": "מנוחה ושמחה", "artistName": "מקהלת שירת הים",
                             "collectionName": "שבת", "trackTimeMillis": 214000, "releaseDate": "2019-01-01"}]}, ""
    return {"results": [{"kind": "song", "trackName": "Something Else", "artistName": "X",
                         "trackTimeMillis": 100000}]}, ""


def test_the_library_job_fills_only_sure_matches_and_remembers(tmp_path):
    from hamenagen.service import PlayerService

    svc = PlayerService(tmp_path)
    svc.index.upsert_many([
        Track(id="a", path="/m/a.mp3", title="מנוחה ושמחה", artist="", duration=213.0, filename="a.mp3"),
        Track(id="b", path="/m/b.mp3", title="שיר אחר", artist="", duration=180.0, filename="b.mp3"),
        Track(id="c", path="/m/c.mp3", title="עם תמונה", artist="זמר", duration=180.0, cover="k", filename="c.mp3"),
    ])
    events = []
    out = svc.complete_details(events.append, pause=0, fetch=fake_itunes)
    assert out == {"ok": True, "done": 2, "found": 1, "total": 2, "stopped": False, "message": ""}
    assert svc.index.get("a").artist == "מקהלת שירת הים"          # filled in
    assert svc.index.get("b").artist == ""                         # nothing sure: left alone
    assert events[-1] == {"done": 2, "total": 2, "found": 1}
    # Looked up once: not again.
    assert svc.complete_details(pause=0, fetch=fake_itunes)["total"] == 0


def test_a_blocked_network_stops_the_job(tmp_path):
    from hamenagen.service import PlayerService

    svc = PlayerService(tmp_path)
    svc.index.upsert(Track(id="a", path="/m/a.mp3", title="x", duration=100.0, filename="a.mp3"))
    out = svc.complete_details(pause=0, fetch=lambda url, params: (None, "blocked"))
    assert not out["ok"] and "נטפרי" in out["message"] and out["done"] == 0
    assert svc.index.details() == {}                                # not marked: tried again later
