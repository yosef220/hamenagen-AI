"""1.7: a singer's songs to pick from on the downloads page, and new songs
from the singers the listener follows."""

from hamenagen import singers_online as so
from hamenagen.fetcher import FetchOutcome, SearchResult
from hamenagen.models import Track
from hamenagen.service import PlayerService

CID = "UC" + "a" * 22
OTHER = "UC" + "b" * 22


def _r(vid, title, cid=CID, channel="Eli Herzlich"):
    return SearchResult("youtube", vid, title, f"https://www.youtube.com/watch?v={vid}", channel=channel,
                        uploader=channel, channel_id=cid, channel_url=f"https://www.youtube.com/channel/{cid}")


def _feed(*entries):
    items = "".join(
        f"<entry><yt:videoId>{vid}</yt:videoId><yt:channelId>{CID}</yt:channelId><title>{title}</title>"
        f"<author><name>Eli Herzlich</name></author><published>2026-11-{day:02d}T10:00:00+00:00</published>"
        f'<media:group><media:thumbnail url="https://i.ytimg.com/vi/{vid}/hqdefault.jpg"/></media:group></entry>'
        for vid, title, day in entries)
    return ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">'
            f"{items}</feed>").encode()


class _Fetcher:
    def __init__(self):
        self.links = []

    def available(self):
        return True

    def search(self, query, limit=5):
        return FetchOutcome(True, results=[_r("aaaaaaaaaaa", "אלי הרצליך - המלאך"), _r("bbbbbbbbbbb", "אלי הרצליך - כל תפילותיי"),
                                           _r("ccccccccccc", "שיר אחר", OTHER, "Someone")])

    def link_info(self, url, limit=300):
        self.links.append(url)
        return FetchOutcome(True, kind="list", results=[_r("aaaaaaaaaaa", "אלי הרצליך - המלאך"),
                                                        _r("ddddddddddd", "אלי הרצליך - ניגון חדש")])


def test_the_main_channel_needs_most_results():
    assert so.main_channel([_r("a" * 11, "x"), _r("b" * 11, "y"), _r("c" * 11, "z", OTHER)]).id == CID
    assert so.main_channel([_r("a" * 11, "x"), _r("c" * 11, "z", OTHER)]) is None


def test_the_feed_is_read():
    got = so.parse_feed(_feed(("eeeeeeeeeee", "אלי הרצליך - חדש", 20), ("bad", "x", 1)))
    assert [(r.id, r.title, r.upload_date, r.channel_id) for r in got] == [("eeeeeeeeeee", "אלי הרצליך - חדש", "20261120", CID)]
    assert got[0].thumbnail.endswith("hqdefault.jpg")
    assert so.parse_feed(b"<html>blocked</html>") == []


def test_a_singers_songs_marks_what_is_here(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.fetcher = _Fetcher()
        service.index.upsert(Track(id="1", path="/m/x.mp3", title="המלאך", artist="אלי הרצליך"))
        out = service.singer_songs("אלי הרצליך")
        assert out["ok"] and out["channel"]["id"] == CID and not out["followed"]
        assert service.fetcher.links == [f"https://www.youtube.com/channel/{CID}/videos"]
        assert [(r["id"], r["in_library"]) for r in out["results"]] == [("aaaaaaaaaaa", True), ("ddddddddddd", False)]
    finally:
        service.close()


def test_following_offers_only_what_comes_after(tmp_path, monkeypatch):
    feeds = [_feed(("aaaaaaaaaaa", "אלי הרצליך - המלאך", 1)),
             _feed(("eeeeeeeeeee", "אלי הרצליך - שיר חדש", 20), ("aaaaaaaaaaa", "אלי הרצליך - המלאך", 1))]
    monkeypatch.setattr("hamenagen.network.get_bytes", lambda url, **kw: feeds.pop(0) if feeds else None)
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.fetcher = _Fetcher()
        r = service.follow_singer("אלי הרצליך", CID, True)
        assert r["ok"] and service.settings.followed_singers[0]["channel_id"] == CID
        assert service.singer_songs("אלי הרצליך")["followed"]
        new = service.followed_new(force=True)["new"]
        assert [(n["id"], n["singer"]) for n in new] == [("eeeeeeeeeee", "אלי הרצליך")]
        service.dismiss_new("eeeeeeeeeee")
        assert service.followed_new()["new"] == []
        service.follow_singer("אלי הרצליך", CID, False)
        assert service.settings.followed_singers == []
        assert not service.follow_singer("x", "not-a-channel")["ok"]
    finally:
        service.close()
