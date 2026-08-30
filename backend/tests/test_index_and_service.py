from datetime import datetime, timedelta

from hamenagen.index_db import MusicIndex
from hamenagen.models import Track


def _track(i, **kw):
    base = dict(
        id=str(i),
        path=f"/music/song{i}.mp3",
        title=f"שיר {i}",
        filename=f"song{i}.mp3",
    )
    base.update(kw)
    return Track(**base)


def test_upsert_and_count():
    with MusicIndex(":memory:") as idx:
        idx.upsert(_track(1))
        idx.upsert(_track(2))
        assert idx.count() == 2
        # upsert same id updates, does not duplicate
        idx.upsert(_track(1, title="שיר מעודכן"))
        assert idx.count() == 2
        assert idx.get("1").title == "שיר מעודכן"


def test_by_topic():
    with MusicIndex(":memory:") as idx:
        idx.upsert(_track(1, topic="שבת"))
        idx.upsert(_track(2, topic="חנוכה"))
        idx.upsert(_track(3, topic="שבת"))
        assert len(idx.by_topic("שבת")) == 2


def test_recent_downloaded_order():
    now = datetime(2026, 1, 1)
    with MusicIndex(":memory:") as idx:
        idx.upsert(_track(1, download_date=(now - timedelta(days=3)).isoformat()))
        idx.upsert(_track(2, download_date=(now - timedelta(days=1)).isoformat()))
        idx.upsert(_track(3, download_date=(now - timedelta(days=2)).isoformat()))
        recent = idx.recent_downloaded(10)
        assert [t.id for t in recent] == ["2", "3", "1"]


def test_delete_missing():
    with MusicIndex(":memory:") as idx:
        idx.upsert(_track(1))
        idx.upsert(_track(2))
        removed = idx.delete_missing({"1"})
        assert removed == 1
        assert idx.count() == 1
