"""1.7.4: the singer's songs from the page the window's browser reads (Google
keeps its results in scripts, Bing and DuckDuckGo behind their own addresses),
a pasted link in the singer's box, and downloads in the singer's folder — an
album in a folder of its own in it."""

import base64
from pathlib import Path

from hamenagen import websearch
from hamenagen.fetcher import FetchOutcome, SearchResult
from hamenagen.service import PlayerService, folder_name, place_download

CID = "UC" + "a" * 22


def _r(vid, title, channel="Eli Herzlich"):
    return SearchResult("youtube", vid, title, f"https://www.youtube.com/watch?v={vid}", channel=channel,
                        uploader=channel, channel_id=CID, channel_url=f"https://www.youtube.com/channel/{CID}")


class _Fetcher:
    """YouTube's search blocked; channel pages open unless "wrong" is in them."""

    def __init__(self):
        self.links = []

    def available(self):
        return True

    def search(self, query, limit=5):
        return FetchOutcome(False, "חסום", code="netfree", blocked=True)

    def link_info(self, url, limit=300):
        self.links.append(url)
        if "wrong" in url:
            return FetchOutcome(False, "חסום", code="netfree", blocked=True)
        if "watch?v=" in url:
            return FetchOutcome(True, kind="video", results=[_r(url[-11:], "אלי הרצליך - המלאך")])
        return FetchOutcome(True, kind="list", artist="Eli Herzlich", title="Eli Herzlich - Videos",
                            results=[_r("aaaaaaaaaaa", "אלי הרצליך - המלאך"), _r("bbbbbbbbbbb", "אלי הרצליך - ניגון")])


# -- the page ------------------------------------------------------------------------------
def test_google_keeps_its_links_in_scripts():
    page = ('<script>var d=["https://www.youtube.com/watch?v\\u003donIGd_jaQ2k\\u0026t\\u003d1",'
            '"https:\\/\\/www.youtube.com\\/user\\/EliHerzlichOfficial"];</script>'
            '<a href="/search?q=x">x</a>')
    assert websearch.extract_video_ids(page) == ["onIGd_jaQ2k"]
    assert websearch.extract_channels(page) == ["https://www.youtube.com/user/EliHerzlichOfficial"]


def test_duckduckgo_and_bing_send_results_through_their_own_addresses():
    ddg = ('<a href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.youtube.com%2Fchannel%2F'
           'UCOCt1faxauheh_C%2DXY2eG7Q&amp;rut=96">Eli Herzlich - YouTube</a>')
    assert websearch.extract_channels(ddg) == ["https://www.youtube.com/channel/UCOCt1faxauheh_C-XY2eG7Q"]
    link = base64.urlsafe_b64encode(b"https://www.youtube.com/watch?v=SsMUjSB8UaY").decode().rstrip("=")
    bing = f'<a href="https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1{link}&amp;ntb=1">x</a>'
    assert websearch.extract_video_ids(bing) == ["SsMUjSB8UaY"]
    assert websearch.extract_video_ids("<html>nothing here</html>") == []


def test_the_channel_named_in_the_page_opens(tmp_path, monkeypatch):
    monkeypatch.setattr("hamenagen.fetcher._oembed_result", lambda url, **kw: None)
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.fetcher = _Fetcher()
        page = '<script>["https:\\/\\/www.youtube.com\\/channel\\/' + CID + '"]</script>'
        out = service.singer_from_links("אלי הרצליך", [], page=page)
        assert out["ok"] and not out.get("web_list") and out["channel"]["id"] == CID
        assert out["channel"]["name"] == "Eli Herzlich" and len(out["results"]) == 2
        assert service.fetcher.links == [f"https://www.youtube.com/channel/{CID}/videos"]
    finally:
        service.close()


def test_with_no_channel_in_the_page_the_channel_that_uploaded_its_songs(tmp_path, monkeypatch):
    """Google's page for a singer often shows only songs: the channel most of
    them came from (as YouTube's short description, oEmbed, tells) opens."""
    asked = []

    def oembed(url, **kw):
        asked.append(url)
        vid = url[-11:]
        owner = "https://www.youtube.com/@someone" if vid == "ccccccccccc" else "https://www.youtube.com/@EliHerzlich"
        return SearchResult("youtube", vid, f"שיר {vid[:2]}", url, uploader="x", channel="x", channel_url=owner)

    monkeypatch.setattr("hamenagen.fetcher._oembed_result", oembed)
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.fetcher = _Fetcher()
        page = "".join(f'"https://www.youtube.com/watch?v\\u003d{v}"' for v in ("aaaaaaaaaaa", "ccccccccccc", "bbbbbbbbbbb"))
        out = service.singer_from_links("אלי הרצליך", [], page=page)
        assert out["ok"] and not out.get("web_list") and out["channel"]["name"] == "Eli Herzlich"
        assert service.fetcher.links[0] == "https://www.youtube.com/@EliHerzlich/videos"
        assert len(asked) == 3
    finally:
        service.close()


def test_when_no_channel_opens_the_songs_get_their_names(tmp_path, monkeypatch):
    monkeypatch.setattr("hamenagen.fetcher._oembed_result", lambda url, **kw: SearchResult(
        "youtube", url[-11:], "אלי הרצליך - כל תפילותיי", url, channel="Eli", channel_url="https://www.youtube.com/@wrong"))
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.fetcher = _Fetcher()
        out = service.singer_from_links("אלי הרצליך", [], page='"https://www.youtube.com/watch?v\\u003daaaaaaaaaaa"')
        assert out["ok"] and out["web_list"]
        assert [(r["id"], r["title"]) for r in out["results"]] == [("aaaaaaaaaaa", "אלי הרצליך - כל תפילותיי")]
    finally:
        service.close()


# -- a link in the singer's box -----------------------------------------------------------------
def test_a_channel_link_opens_as_it_is(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.fetcher = _Fetcher()
        out = service.singer_songs("https://www.youtube.com/channel/UCJxECluw4yBOJChpzKwxjSA")
        assert out["ok"] and out["channel"]["id"] == CID and len(out["results"]) == 2
        assert service.fetcher.links == ["https://www.youtube.com/channel/UCJxECluw4yBOJChpzKwxjSA/videos"]
        # A song's link: the channel that uploaded it.
        service.fetcher.links.clear()
        out = service.singer_songs("https://youtu.be/aaaaaaaaaaa")
        assert out["ok"] and service.fetcher.links[-1] == f"https://www.youtube.com/channel/{CID}/videos"
        # A channel that does not open says so, without a search.
        out = service.singer_songs("https://www.youtube.com/@wrong")
        assert not out["ok"] and out["code"] == "link" and out["blocked"]
    finally:
        service.close()


# -- folders ----------------------------------------------------------------------------------
def test_folder_names_windows_accepts():
    assert folder_name('אלי הרצליך: "הכל" / חי?') == "אלי הרצליך הכל חי"
    assert folder_name("Album. ") == "Album"
    assert folder_name("CON") == ""
    assert len(folder_name("א" * 200)) == 80


def test_a_download_goes_to_the_singers_folder_and_an_album_to_its_own(tmp_path):
    downloads = tmp_path / "dl"
    downloads.mkdir()
    song = downloads / "song [aaaaaaaaaaa].mp3"
    song.write_bytes(b"x")
    moved = place_download(song, downloads, "אלי הרצליך")
    assert moved == downloads / "אלי הרצליך" / "song [aaaaaaaaaaa].mp3" and moved.exists() and not song.exists()
    other = downloads / "song [aaaaaaaaaaa].mp3"
    other.write_bytes(b"y")
    in_album = place_download(other, downloads, "אלי הרצליך", "Album - כל תפילותיי")
    assert in_album == downloads / "אלי הרצליך" / "Album - כל תפילותיי" / "song [aaaaaaaaaaa].mp3"
    third = downloads / "song [aaaaaaaaaaa].mp3"
    third.write_bytes(b"z")
    assert place_download(third, downloads, "אלי הרצליך").name == "song [aaaaaaaaaaa] (2).mp3"
    loose = downloads / "x.mp3"
    loose.write_bytes(b"x")
    assert place_download(loose, downloads, "") == loose


class _Downloader(_Fetcher):
    def download(self, result, dest_dir, on_progress=None, cancel=None):
        path = Path(dest_dir) / f"{result.title} [{result.id}].mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ID3" + b"\0" * 64)
        return FetchOutcome(True, path=str(path), result=result, title=result.title, artist="אלי הרצליך")


def test_a_list_downloads_into_the_singer_and_album_folders(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        service.fetcher = _Downloader()
        out = service.download_many([_r("aaaaaaaaaaa", "המלאך"), _r("bbbbbbbbbbb", "ניגון")],
                                    artist="אלי הרצליך", album="כל תפילותיי")
        assert out["downloaded"] == 2
        album = service.downloads_dir / "אלי הרצליך" / "כל תפילותיי"
        assert sorted(p.name for p in album.iterdir()) == ["המלאך [aaaaaaaaaaa].mp3", "ניגון [bbbbbbbbbbb].mp3"]
        # One song: in the singer's folder, by the singer the song's name gives.
        one = service.download_and_add(_r("ccccccccccc", "שיר"))
        assert Path(one["path"]).parent == service.downloads_dir / "אלי הרצליך"
    finally:
        service.close()
