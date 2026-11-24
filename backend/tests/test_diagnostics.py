"""1.7: the diagnostics report, and full speed in the background on Windows."""

from hamenagen import winpower
from hamenagen.fetcher import FetchOutcome, SearchResult
from hamenagen.service import PlayerService


class _BlockedFetcher:
    def download(self, result, dest, on_progress=None, cancel=None):
        on_progress({"status": "downloading", "percent": 3.0})
        return FetchOutcome(False, "הסרטון הזה חסום", code="netfree", blocked=True,
                            detail="[youtube] x: Downloading webpage\nERROR: HTTP Error 418: Blocked by NetFree")


def test_the_report_holds_the_last_failure_with_its_stages(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        (service.data_dir / "logs").mkdir(exist_ok=True)
        (service.data_dir / "logs" / "core.log").write_text("line one\nline two\n", encoding="utf-8")
        service.fetcher = _BlockedFetcher()
        r = service.download_and_add(SearchResult("youtube", "abcdefghijk", "המלאך", "https://youtu.be/abcdefghijk"))
        assert not r["ok"] and r["code"] == "netfree"
        out = service.diagnostics_report()
        text = open(out["path"], encoding="utf-8").read()
        assert "דוח אבחון" in text and "yt-dlp" in text and "מנוע JS" in text
        assert "המלאך — https://youtu.be/abcdefghijk" in text and "netfree" in text
        assert "downloading" in text and "Blocked by NetFree" in text
        assert text.rstrip().endswith("line two")
    finally:
        service.close()


def test_no_throttling_does_nothing_off_windows():
    import os

    if os.name != "nt":
        assert winpower.no_throttling() is False
