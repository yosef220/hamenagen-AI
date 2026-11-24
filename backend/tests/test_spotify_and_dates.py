"""1.7: Spotify links become songs to download from YouTube, and the songs of
a channel or a search come with the date they came out."""

import json

from hamenagen import spotify
from hamenagen.fetcher import _entry_result
from hamenagen.service import PlayerService


def _page(entity):
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


PLAYLIST = {"type": "playlist", "name": "שבת", "trackList": [
    {"uri": "spotify:track:" + "a" * 22, "title": "מנוחה ושמחה", "subtitle": "ישי ריבו, אחר", "duration": 245000},
    {"uri": "spotify:track:" + "b" * 22, "title": "לכה דודי", "subtitle": "אברהם פריד", "duration": 301500},
]}


def test_links():
    assert spotify.parse_link("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x") == ("playlist", "37i9dQZF1DXcBWIGoYBM5M")
    assert spotify.parse_link("https://open.spotify.com/intl-he/album/4aawyAB9vmqN3uQ7FjRGTy") == ("album", "4aawyAB9vmqN3uQ7FjRGTy")
    assert spotify.parse_link("spotify:track:2sFepQNyl1WjpROruP8bJ0") == ("track", "2sFepQNyl1WjpROruP8bJ0")
    assert spotify.parse_link("https://www.youtube.com/watch?v=x") is None


def test_the_embed_page_is_read():
    name, songs = spotify.parse_embed(_page(PLAYLIST))
    assert name == "שבת" and [(s.title, s.artists, s.seconds) for s in songs] == [
        ("מנוחה ושמחה", "ישי ריבו, אחר", 245.0), ("לכה דודי", "אברהם פריד", 301.5)]
    name, songs = spotify.parse_embed(_page({"type": "track", "name": "Housewife", "uri": "spotify:track:" + "c" * 22,
                                            "artists": [{"name": "Tate McRae"}], "duration": 208810}))
    assert [(s.title, s.artists) for s in songs] == [("Housewife", "Tate McRae")]
    assert spotify.parse_embed("<html>blocked</html>") == ("", [])
    r = spotify.as_result(spotify.Song("מנוחה ושמחה", "ישי ריבו, אחר", 245.0, "a" * 22))
    assert r.url == "ytsearch1:ישי ריבו מנוחה ושמחה" and r.title == "ישי ריבו - מנוחה ושמחה" and r.duration == 245.0


def test_a_spotify_link_lists_its_songs(tmp_path, monkeypatch):
    monkeypatch.setattr("hamenagen.network.get_bytes", lambda url, **kw: _page(PLAYLIST).encode())
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        out = service.spotify_link("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        assert out["ok"] and out["kind"] == "list" and out["title"] == "מספוטיפיי: שבת"
        assert [r["url"] for r in out["results"]] == ["ytsearch1:ישי ריבו מנוחה ושמחה", "ytsearch1:אברהם פריד לכה דודי"]
        assert not service.spotify_link("https://example.com")["ok"]
    finally:
        service.close()


def test_dates_on_lists():
    exact = _entry_result({"id": "abcdefghijk", "title": "x", "upload_date": "20240315"})
    assert (exact.upload_date, exact.date_approx) == ("20240315", False)
    approx = _entry_result({"id": "abcdefghijk", "title": "x", "timestamp": 1710460800})   # 2024-03-15 UTC
    assert (approx.upload_date, approx.date_approx) == ("20240315", True)
    none = _entry_result({"id": "abcdefghijk", "title": "x"})
    assert none.upload_date is None and not none.date_approx
