"""Tests for the radio channel parsing + offline fallback (spec §13)."""

from hamenagen.radio import RadioProvider, parse_server_model, stations_from_model

SAMPLE_HTML = """
<html><body>
<script>
  var ServerModel = {"live":[
    {"id":1,"title":"שידור חי","url":"https://live.kcm.fm/livemusic","playing":"שיר א","image":11391,"visible":1,"order":3010,"short":"הראשי","cat":2,"name":"קול חי"},
    {"id":17,"title":"תענוג לשבת","url":"https://live.kcm.fm/17/hls.m3u8","playing":"שיר ב","image":5186,"visible":1,"order":1500,"short":"שבת","cat":1,"name":"מני"},
    {"id":99,"title":"מוסתר","url":"https://x/hidden","visible":0,"order":5,"image":0}
  ]};
  var serverDate = "x";
</script>
</body></html>
"""


def test_parse_and_map():
    model = parse_server_model(SAMPLE_HTML)
    stations = stations_from_model(model)
    # Hidden (visible=0) channel is dropped.
    assert len(stations) == 2
    # Sorted by order desc: livemusic (3010) before שבת (1500).
    assert stations[0].id == 1
    assert stations[0].url == "https://live.kcm.fm/livemusic"
    assert stations[1].title == "תענוג לשבת"
    # Image URL derived from id//1000 folder.
    assert stations[0].image_url == "https://kcm.fm/upload/pictures/11/11391.jpg"
    assert stations[0].now_playing == "שיר א"


def test_offline_falls_back_to_seed(tmp_path):
    # Unreachable source + no cache -> bundled seed.
    provider = RadioProvider(
        "http://127.0.0.1:9/definitely-not-listening",
        cache_path=tmp_path / "cache.json",
    )
    result = provider.list(refresh=True)
    assert result["online"] is False
    assert result["source"] == "seed"
    assert result["count"] > 0
    # Seed includes the main Kol Chai live stream.
    assert any(s["url"] == "https://live.kcm.fm/livemusic" for s in result["stations"])


def test_no_refresh_uses_seed_when_no_cache(tmp_path):
    provider = RadioProvider(cache_path=tmp_path / "cache.json")
    result = provider.list(refresh=False)
    assert result["source"] == "seed"
    assert result["count"] > 0


def test_more_stations_and_the_listeners_own(tmp_path):
    from hamenagen.radio import MORE_STATIONS, RadioProvider

    rp = RadioProvider(cache_path=tmp_path / "c.json", seed_path=tmp_path / "none.json")
    rp.custom = [{"title": "שלי", "url": "https://example.org/live"}, {"title": "x", "url": "http://insecure"}]
    out = rp.list(refresh=False)
    titles = [s["title"] for s in out["stations"]]
    assert all(s.title in titles for s in MORE_STATIONS)
    mine = [s for s in out["stations"] if s["custom"]]
    assert [s["title"] for s in mine] == ["שלי"] and mine[0]["group"] == "התחנות שלי"
    assert all(s["url"].startswith("https://") for s in out["stations"] if s["group"])


def test_custom_stations_are_cleaned_in_settings():
    from hamenagen.settings import Settings

    s = Settings()
    s.update({"custom_stations": [{"title": " א ", "url": "https://a.example/live"}, {"url": "ftp://x"}, "junk"]})
    assert s.custom_stations == [{"title": "א", "url": "https://a.example/live"}]
