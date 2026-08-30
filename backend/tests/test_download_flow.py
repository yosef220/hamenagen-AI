"""Tests for the online-completion tail (spec §11) using a fake source.

We avoid any network by injecting a fake SourcePlugin that "downloads" by
creating a local file, so we can verify the service wiring: the file is added
to the index, classified, given a release date from the source's upload date,
and progress callbacks fire.
"""

from pathlib import Path

from hamenagen.fetcher import FetchOutcome, SearchResult
from hamenagen.service import PlayerService


class FakeSource:
    name = "youtube"

    def __init__(self, tmp: Path):
        self.tmp = tmp

    def available(self):
        return True

    def search_url(self, query):
        return "https://example/results?q=" + query

    def search(self, query, *, limit=5):
        r = SearchResult(self.name, "abc123", "נרות חנוכה", "https://x/abc123", "להקה")
        return FetchOutcome(True, "", result=r, results=[r])

    def download(self, result, dest_dir, *, on_progress=None):
        if on_progress:
            on_progress({"status": "downloading", "percent": 50.0})
            on_progress({"status": "finished"})
        path = Path(dest_dir) / f"{result.title} [{result.id}].mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-audio")
        enriched = SearchResult(
            self.name, result.id, result.title, result.url, result.uploader,
            duration=123, upload_date="20241226",
        )
        return FetchOutcome(True, "ההורדה הושלמה.", path=str(path), result=enriched)


def test_download_and_add_indexes_and_classifies(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")
    service.settings.use_embeddings = False
    service.fetcher.source = FakeSource(tmp_path / "dl")

    events = []
    result = SearchResult("youtube", "abc123", "נרות חנוכה", "https://x/abc123", "להקה")
    out = service.download_and_add(result, on_progress=lambda d: events.append(d))

    assert out["ok"] is True
    track = out["track"]
    assert track is not None
    # Added to the local index.
    assert service.index.count() == 1
    # Classified via the curated keyword "נרות"/"חנוכה".
    assert track["topic"] == "חנוכה"
    assert track["source"] == "youtube"
    # Upload date became the release date (spec §10 note).
    assert track["release_date"] == "2024-12-26"
    # Progress was reported.
    assert any(e.get("status") == "downloading" for e in events)
    service.close()


def test_download_failure_reports_message(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")

    class Failing(FakeSource):
        def download(self, result, dest_dir, *, on_progress=None):
            return FetchOutcome(False, "הסרטון אינו זמין (הוסר או פרטי).")

    service.fetcher.source = Failing(tmp_path / "dl")
    out = service.download_and_add(
        SearchResult("youtube", "x", "t", "u"), on_progress=None
    )
    assert out["ok"] is False
    assert "אינו זמין" in out["message"]
    assert service.index.count() == 0
    service.close()
