"""1.2: every word must match; YouTube through a process that can be
stopped; NetFree reported clearly; details from the web on request.

Nothing here touches the network: the yt-dlp process is a fake script or a
fake runner, and the web lookups are fakes."""

import sys
import threading
from pathlib import Path

import pytest

from hamenagen import metadata
from hamenagen.fetcher import (
    FetchOutcome,
    OnlineFetcher,
    SearchResult,
    YouTubeSource,
    clean_video_title,
    parse_youtube_link,
)
from hamenagen.fuzzy import MatchCandidate as C, near_matches, search
from hamenagen.service import PlayerService
from hamenagen.ytdlp_runner import RunResult, YtDlpRunner, classify_error

SONG_BYTES = b"\0" * (70 * 1024)

LIBRARY = [
    C("1", title="לך אלי", artist="ישי ריבו", album='אלול תשע"ט'),
    C("2", title="אלי שבשמים", artist="חיים ישראל", album="ירושלים"),
    C("3", title="ממך עד אלי", artist="חנן בן ארי", album="איזון"),
    C("4", title="ואם תבואי אלי", filename="03 ואם תבואי אלי.wma"),
    C("5", title="המלאך", artist="אלי הרצליך"),
    C("6", title="רק לתת", artist="אלי הרצליך"),
]


# ------------------------------------------------------------------ search
def test_a_singers_name_finds_only_that_singer():
    ids = [m.candidate.id for m in search("אלי הרצליך", LIBRARY)]
    assert sorted(ids) == ["5", "6"]


def test_one_shared_word_is_not_a_match():
    assert search("אלי גולדברג", LIBRARY) == []
    assert near_matches("אלי גולדברג", LIBRARY) == []  # two words: no "near" either


def test_typos_prefixes_and_folders():
    assert [m.candidate.id for m in search("אלי הרצלך", LIBRARY)][:2] == ["6", "5"] or \
        sorted(m.candidate.id for m in search("אלי הרצלך", LIBRARY)) == ["5", "6"]
    assert sorted(m.candidate.id for m in search("רצליך", LIBRARY)) == ["5", "6"]  # הרצליך with ה
    in_folder = [C("9", title="רצועה 19", folder="אלי הרצליך")]
    assert [m.candidate.id for m in search("אלי הרצליך", in_folder)] == ["9"]


def test_a_long_request_missing_one_word_is_offered_as_near():
    assert search("לך אלי ישי ריבו לייב", LIBRARY) == []
    assert [m.candidate.id for m in near_matches("לך אלי ישי ריבו לייב", LIBRARY)] == ["1"]


def _library(root, names):
    root.mkdir(parents=True, exist_ok=True)
    for n in names:
        (root / n).write_bytes(SONG_BYTES)
    return root


def _service(tmp_path):
    s = PlayerService(data_dir=tmp_path / "data")
    s.settings.use_embeddings = False
    s.classifier.embedding = None
    return s


def test_requests_for_a_singer(tmp_path):
    music = _library(tmp_path / "music", [
        "אלי הרצליך - המלאך.mp3", "אלי הרצליך - רק לתת.mp3", "ישי ריבו - לך אלי.mp3",
        "חיים ישראל - אלי שבשמים.mp3", "03 ואם תבואי אלי.mp3",
    ])
    s = _service(tmp_path)
    s.rescan([str(music)])
    res = s.handle_request("אלי הרצליך")
    assert sorted(t["title"] for t in res["tracks"]) == ["המלאך", "רק לתת"]
    assert res["understood"] == "השירים של אלי הרצליך"
    missing = s.handle_request("אלי גולדברג")
    assert missing["tracks"] == [] and missing["found_local"] is False and "לא נמצא" in missing["note"]
    near = s.handle_request("תשמיע לך אלי של ישי ריבו בהופעה")
    assert near["near"] is True and [t["title"] for t in near["tracks"]] == ["לך אלי"]
    s.close()


# ------------------------------------------------------------------ names and links
@pytest.mark.parametrize("title,channel,expected", [
    ("אלי הרצליך - כל תפילותיי הקליפ הרשמי | Eli Herzlich - Kol Tefilotai Official Music Video", "Eli Herzlich",
     ("אלי הרצליך", "כל תפילותיי")),
    ("אלי הרצליך, אלי קליין ואבי דרור - בזכות התורה | שירת המונים - בני ברק", "Eli Herzlich",
     ("אלי הרצליך, אלי קליין ואבי דרור", "בזכות התורה")),
    ("Shmulik Suchot - Emet (Official Video)", "", ("Shmulik Suchot", "Emet")),
    ("המלאך", "Eli Herzlich", ("Eli Herzlich", "המלאך")),
    ("Lecha Dodi", "Avraham Fried - Topic", ("Avraham Fried", "Lecha Dodi")),
])
def test_clean_names_from_video_titles(title, channel, expected):
    assert clean_video_title(title, channel) == expected


@pytest.mark.parametrize("text,expected", [
    ("https://youtu.be/PCS_sA1OdcM", ("video", "https://www.youtube.com/watch?v=PCS_sA1OdcM")),
    ("שמעתי את זה: https://www.youtube.com/watch?v=PCS_sA1OdcM&t=30s", ("video", "https://www.youtube.com/watch?v=PCS_sA1OdcM")),
    ("https://www.youtube.com/shorts/PCS_sA1OdcM", ("video", "https://www.youtube.com/watch?v=PCS_sA1OdcM")),
    ("https://www.youtube.com/@EliHerzlich", ("channel", "https://www.youtube.com/@EliHerzlich/videos")),
    ("https://www.youtube.com/channel/UCOCt1faxauheh_C-XY2eG7Q/featured",
     ("channel", "https://www.youtube.com/channel/UCOCt1faxauheh_C-XY2eG7Q/videos")),
    ("https://www.youtube.com/playlist?list=PL123", ("playlist", "https://www.youtube.com/playlist?list=PL123")),
    ("https://example.com/watch?v=PCS_sA1OdcM", None),
    ("סתם טקסט", None),
])
def test_youtube_links_are_recognised(text, expected):
    assert parse_youtube_link(text) == expected


# ------------------------------------------------------------------ the engine process
def test_errors_are_named():
    assert classify_error('ERROR: query "x" page 1: Unable to download API page: HTTP Error 418: Blocked by NetFree') == "netfree"
    assert classify_error("Sign in to confirm you’re not a bot") == "extract"
    assert classify_error("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed") == "certificate"
    assert classify_error("ERROR: [youtube] x: Video unavailable") == "unavailable"
    assert classify_error("urlopen error [Errno 11001] getaddrinfo failed") == "network"


class _ScriptRunner(YtDlpRunner):
    """Runs a small Python script instead of yt-dlp."""

    def __init__(self, script, **kw):
        super().__init__(**kw)
        self.script = script

    def command(self, args, client=None):
        return [sys.executable, "-c", self.script]


def test_a_stuck_process_is_killed_on_time():
    r = _ScriptRunner("import time; time.sleep(30)")
    res = r.run([], timeout=1)
    assert res.killed == "timeout" and not res.ok and res.code == "timeout"


def test_a_silent_process_is_killed_as_stalled_and_lines_stream():
    r = _ScriptRunner("import time, sys; print('[download]  10.0% of 3MiB', flush=True); time.sleep(30)")
    lines = []
    res = r.stream([], lines.append, stall=1)
    assert res.killed == "stalled" and lines == ["[download]  10.0% of 3MiB"]


def test_a_cancelled_process_stops():
    r = _ScriptRunner("import time; time.sleep(30)")
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    assert r.run([], timeout=20, cancel=stop).killed == "cancelled"


def test_a_certificate_error_is_reported_and_the_check_stays_on():
    r = _ScriptRunner("import sys; print('ERROR: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed', file=sys.stderr); sys.exit(1)")
    res = r.run([])
    assert res.code == "certificate" and "תעודת האבטחה" in res.message
    assert "--compat-options" in YtDlpRunner().command([]) and "no-certifi" in YtDlpRunner().command([])


class _FakeRunner:
    """Answers like yt-dlp would, without starting anything."""

    def __init__(self, run_results=(), stream_scripts=()):
        self.run_results = list(run_results)
        self.stream_scripts = list(stream_scripts)
        self.clients = []
        self.ffmpeg = ""
        self.updated = False
        self.update_calls = 0

    def available(self):
        return True

    def run(self, args, *, timeout=30, client=None, cancel=None):
        self.clients.append(client)
        return self.run_results.pop(0)

    def stream(self, args, on_line, *, stall=90, timeout=None, client=None, cancel=None):
        self.clients.append(client)
        lines, result = self.stream_scripts.pop(0)
        for line in lines:
            on_line(line)
        return result

    def json_lines(self, result):
        return YtDlpRunner.json_lines(self, result)

    def update_engine(self):
        self.update_calls += 1
        return {"ok": True, "updated": True}


def test_search_blocked_by_netfree_says_so():
    blocked = RunResult(1, err='ERROR: query "x" page 1: Unable to download API page: HTTP Error 418: Blocked by NetFree')
    src = YouTubeSource(_FakeRunner([blocked]))
    out = src.search("אלי הרצליך")
    assert not out.ok and out.blocked and out.code == "netfree" and "נטפרי" in out.message
    assert src.search_url("אלי הרצליך").startswith("https://www.youtube.com/results?search_query=")


def test_search_results_carry_the_channel():
    line = ('{"id": "PCS_sA1OdcM", "title": "אלי הרצליך - המלאך", "channel": "Eli Herzlich", '
            '"channel_id": "UCOC", "channel_url": "https://www.youtube.com/channel/UCOC", "duration": 306}')
    src = YouTubeSource(_FakeRunner([RunResult(0, out=line)]))
    out = src.search("אלי הרצליך")
    assert out.ok and out.results[0].channel == "Eli Herzlich" and out.results[0].channel_id == "UCOC"


def test_download_tries_other_clients_then_updates_the_engine(tmp_path):
    song = tmp_path / "המלאך [PCS_sA1OdcM].m4a"
    song.write_bytes(b"x")
    fail = RunResult(1, out="ERROR: [youtube] PCS_sA1OdcM: Sign in to confirm you’re not a bot")
    good = ([f"[download]  50.0% of 3MiB", f"HMFILE:{song}",
             'HMINFO:{"id": "PCS_sA1OdcM", "title": "אלי הרצליך - המלאך הקליפ הרשמי", "channel": "Eli Herzlich", '
             '"upload_date": "20181111", "duration": 306}'], RunResult(0))
    runner = _FakeRunner(stream_scripts=[([], fail)] * 4 + [good])
    src = YouTubeSource(runner)
    events = []
    item = SearchResult("youtube", "PCS_sA1OdcM", "המלאך", "https://www.youtube.com/watch?v=PCS_sA1OdcM")
    import hamenagen.fetcher as fetcher_mod

    fetcher_mod_fetch = fetcher_mod.fetch_thumbnail
    fetcher_mod.fetch_thumbnail = lambda vid: None
    try:
        out = src.download(item, tmp_path, on_progress=events.append)
    finally:
        fetcher_mod.fetch_thumbnail = fetcher_mod_fetch
    assert out.ok and out.path == str(song)
    assert (out.artist, out.title) == ("אלי הרצליך", "המלאך")
    assert runner.update_calls == 1 and len(runner.clients) == 5
    assert {"status": "downloading", "percent": 50.0} in events


def test_a_video_netfree_blocks_is_reported_for_that_song(tmp_path):
    blocked = RunResult(1, out="ERROR: [youtube] abc: Unable to download webpage: HTTP Error 418: Blocked by NetFree")
    runner = _FakeRunner(stream_scripts=[([], blocked)])
    out = YouTubeSource(runner).download(SearchResult("youtube", "abcdefghijk", "x", "https://youtu.be/abcdefghijk"), tmp_path)
    assert not out.ok and out.blocked and "חסום" in out.message and len(runner.clients) == 1


# ------------------------------------------------------------------ many songs in a row
class _FakeSource:
    name = "youtube"

    def __init__(self):
        self.calls = []

    def available(self):
        return True

    def search_url(self, q):
        return q

    def search(self, q, *, limit=5):
        return FetchOutcome(False)

    def download(self, result, dest_dir, *, on_progress=None, cancel=None):
        self.calls.append(result.id)
        if result.id == "blockedvid1":
            return FetchOutcome(False, "חסום", code="netfree", blocked=True)
        path = Path(dest_dir) / f"{result.title} [{result.id}].mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(SONG_BYTES)
        return FetchOutcome(True, "ok", path=str(path), result=result, title=result.title, artist="אלי הרצליך")


def test_download_many_skips_what_is_there_and_goes_on_after_a_block(tmp_path):
    s = _service(tmp_path)
    s.fetcher = OnlineFetcher(_FakeSource())
    items = [SearchResult("youtube", vid, title, f"https://youtu.be/{vid}")
             for vid, title in (("aaaaaaaaaaa", "המלאך"), ("blockedvid1", "אסור"), ("bbbbbbbbbbb", "רק לתת"))]
    events = []
    first = s.download_many(items, on_event=events.append)
    assert (first["downloaded"], first["failed"], first["blocked"], first["skipped"]) == (2, 1, 1, 0)
    again = s.download_many(items)
    assert (again["downloaded"], again["skipped"]) == (0, 2)
    assert {e["status"] for e in events if e["type"] == "item"} == {"started", "done", "failed"}
    assert sorted(t.artist for t in s.index.all_tracks()) == ["אלי הרצליך", "אלי הרצליך"]
    s.close()


# ------------------------------------------------------------------ details from the web
ITUNES = {"results": [
    {"kind": "song", "trackName": "המלאך", "artistName": "Eli Herzlich", "collectionName": "Eli Ertzlich 2",
     "releaseDate": "2018-11-11T08:00:00Z", "trackTimeMillis": 306000,
     "artworkUrl100": "https://is1-ssl.mzstatic.com/a/100x100bb.jpg", "trackViewUrl": "https://music.apple.com/x"},
    {"kind": "song", "trackName": "המלאך (Live)", "artistName": "Other", "collectionName": "Live",
     "trackTimeMillis": 250000, "artworkUrl100": ""},
]}


def test_lookup_parses_and_ranks():
    found, err = metadata.search("המלאך", "אלי הרצליך", 305, fetch=lambda url, params: (ITUNES, ""))
    assert err == "" and found[0].artist == "Eli Herzlich" and found[0].year == "2018"
    assert found[0].cover_url.endswith("600x600bb.jpg") and found[0].score > found[1].score
    blocked, err = metadata.search("המלאך", fetch=lambda url, params: (None, "blocked"))
    assert blocked == [] and err == "blocked"


def test_a_hebrew_name_is_never_replaced_by_an_english_one():
    current = {"title": "המלאך", "artist": "אלי הרצליך", "album": "", "release_date": ""}
    chosen = {"title": "HaMalach", "artist": "Eli Herzlich", "album": "Eli Ertzlich 2", "year": "2018"}
    assert metadata.merge(current, chosen) == {"album": "Eli Ertzlich 2", "year": "2018"}
    english = {"title": "Track 19", "artist": "Eli Herzlich", "album": "", "release_date": "2010"}
    assert metadata.merge(english, {"title": "המלאך", "artist": "אלי הרצליך"}) == {"title": "המלאך", "artist": "אלי הרצליך"}


def test_applying_details_keeps_them_and_shares_the_cover(tmp_path, monkeypatch):
    music = _library(tmp_path / "music" / "אלבום", ["רצועה 19.mp3", "רצועה 20.mp3"])
    s = _service(tmp_path)
    s.rescan([str(music)])
    first = next(t for t in s.index.all_tracks() if "19" in t.filename)
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 5000
    monkeypatch.setattr(metadata, "fetch_image", lambda url: jpeg)
    out = s.apply_details(first.id, {"title": "המלאך", "artist": "אלי הרצליך", "album": "המלאך", "year": "2018",
                                     "cover_url": "https://is1-ssl.mzstatic.com/a/600x600bb.jpg", "url": "https://x"})
    assert out["ok"] and out["cover"] and out["propagated"] == 1
    assert (out["track"]["title"], out["track"]["artist"]) == ("המלאך", "אלי הרצליך")
    # The details survive the next full read of the files.
    s.index.set_meta("scan_version", "1")
    monkeypatch.setattr(s, "_roots", lambda: [str(music)])
    s.rescan()
    again = s.index.get(first.id)
    assert (again.title, again.artist) == ("המלאך", "אלי הרצליך") and again.cover
    other = next(t for t in s.index.all_tracks() if t.id != first.id)
    assert other.cover == again.cover
    s.close()
