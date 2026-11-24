"""1.7: downloads behind a content filter — the regular file when the audio
alone is blocked, a block video never kept as a song — and the order of
YouTube's player clients, from the project and from what worked here."""

import json

from hamenagen import engine_cfg
from hamenagen import fetcher as fetcher_mod
from hamenagen.fetcher import SearchResult, YouTubeSource, looks_replaced
from hamenagen.ytdlp_runner import RunResult, YtDlpRunner
from tests.test_search_and_online import _FakeRunner

BLOCKED = RunResult(1, out="ERROR: [youtube] x: Unable to download video data: HTTP Error 418: Blocked by NetFree")


def _mp3(path, seconds):
    """A real (silent) MPEG-1 Layer III stream of about ``seconds``."""
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413          # 128 kbps, 44.1 kHz: 26 ms a frame
    path.write_bytes(frame * int(seconds / 0.026122))
    return path


class _ArgsFake(_FakeRunner):
    def __init__(self, scripts):
        super().__init__(stream_scripts=scripts)
        self.ffmpeg = "ffmpeg"          # MP3: the regular file can become one
        self.formats = []

    def stream(self, args, on_line, **kw):
        self.formats.append(args[args.index("-f") + 1])
        return super().stream(args, on_line, **kw)


def _item():
    return SearchResult("youtube", "PCS_sA1OdcM", "המלאך", "https://www.youtube.com/watch?v=PCS_sA1OdcM", duration=200)


def _done(path, duration=200):
    return ([f"HMFILE:{path}", 'HMINFO:' + json.dumps({"id": "PCS_sA1OdcM", "title": "המלאך", "duration": duration})],
            RunResult(0))


def test_the_regular_file_when_the_audio_alone_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher_mod, "tag_file", lambda *a, **k: True)
    song = _mp3(tmp_path / "המלאך [PCS_sA1OdcM].mp3", 200)
    runner = _ArgsFake([([], BLOCKED), _done(song)])
    out = YouTubeSource(runner).download(_item(), tmp_path)
    assert out.ok and out.path == str(song)
    assert runner.formats[0] == "bestaudio/best" and runner.formats[1].startswith("18/")


def test_a_block_video_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher_mod, "tag_file", lambda *a, **k: True)
    block = _mp3(tmp_path / "block.mp3", 8)
    block2 = _mp3(tmp_path / "block2.mp3", 8)
    runner = _ArgsFake([_done(block), _done(block2)])
    out = YouTubeSource(runner).download(_item(), tmp_path)
    assert not out.ok and out.code == "replaced" and out.blocked and "קובץ חסימה" in out.message
    assert not block.exists() and not block2.exists()
    assert len(runner.formats) == 2          # the regular file was tried too


def test_what_counts_as_a_block_video(tmp_path):
    assert looks_replaced(_mp3(tmp_path / "a.mp3", 8), 200)
    assert looks_replaced(_mp3(tmp_path / "b.mp3", 50), 200)
    assert not looks_replaced(_mp3(tmp_path / "c.mp3", 190), 200)
    assert not looks_replaced(_mp3(tmp_path / "d.mp3", 8), 30)        # a short song is a short song
    assert not looks_replaced(_mp3(tmp_path / "e.mp3", 8), None)


def test_a_download_asks_for_short_requests():
    runner = _ArgsFake([])
    captured = {}

    def stream(args, on_line, **kw):
        captured["args"] = args
        return RunResult(1, out="ERROR: Video unavailable")

    runner.stream = stream
    YouTubeSource(runner).download(_item(), "/tmp/hamenagen-test-none")
    assert captured["args"][captured["args"].index("--http-chunk-size") + 1] == "10M"


def test_the_order_comes_from_the_project_and_what_worked_here(tmp_path):
    doc = {"rev": 2, "profiles": ["player_client=tv,web_embedded;skip=hls", "", "--exec evil", "android_vr,web"]}
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps(doc).encode()

    got = engine_cfg.refresh(tmp_path, fetch, now=1e10)
    assert got == ["player_client=tv,web_embedded;skip=hls", None, "android_vr,web"]
    assert calls == [engine_cfg.URL]
    engine_cfg.refresh(tmp_path, fetch)          # read moments ago: not again
    assert len(calls) == 1
    runner = YtDlpRunner()
    runner.profiles, runner.state_dir = got, tmp_path
    assert runner.client_order()[0] == "player_client=tv,web_embedded;skip=hls"
    runner.remember("android_vr,web")
    assert runner.client_order() == ["android_vr,web", "player_client=tv,web_embedded;skip=hls", None]
    runner.remember(None)
    assert runner.client_order()[0] is None


def test_a_broken_file_from_the_project_changes_nothing(tmp_path):
    assert engine_cfg.refresh(tmp_path, lambda url: b"<html>blocked</html>") == []
    assert engine_cfg.refresh(tmp_path, lambda url: None, now=1e10) == []


def test_the_projects_own_file_is_valid():
    from pathlib import Path

    doc = json.loads((Path(__file__).resolve().parents[2] / "engine.json").read_text(encoding="utf-8"))
    assert len(engine_cfg.clean_profiles(doc["profiles"])) == len(doc["profiles"])
