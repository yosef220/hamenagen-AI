"""Each song once, and saved playlists."""

from hamenagen.index_db import MusicIndex
from hamenagen.models import Track


def track(tid, path, title, artist="", duration=200.0, size=4_000_000, cover="", album=""):
    return Track(id=tid, path=path, title=title, artist=artist, duration=duration, size=size,
                 filename=path.rsplit("/", 1)[-1], cover=cover, album=album)


def library():
    idx = MusicIndex(":memory:")
    idx.upsert_many([
        # The same song in two folders and two formats.
        track("a1", "/m/שבת/לכה דודי.mp3", "לכה דודי", "אברהם פריד", 241.0),
        track("a2", "/m/גיבוי/לכה דודי.flac", "לכה דודי", "אברהם פריד", 241.6, size=30_000_000),
        # The same name, but another singer: another song.
        track("b1", "/m/לכה דודי - שלמה.mp3", "לכה דודי", "שלמה כהן", 241.0),
        # The same name and singer, but a long live version.
        track("c1", "/m/הופעה/לכה דודי.mp3", "לכה דודי", "אברהם פריד", 402.0),
        # A copy without tags of a tagged song (renamed file, same bytes).
        track("d1", "/m/מנוחה ושמחה.mp3", "מנוחה ושמחה", "מקהלה", 180.0, size=3_100_000),
        track("d2", "/m/x/track07.mp3", "track07", "", 180.2, size=3_100_000),
    ])
    return idx


def test_marks_copies_and_keeps_the_best_one():
    idx = library()
    assert idx.mark_duplicates() == 2
    shown = {t.id for t in idx.list_tracks(limit=50)["tracks"]}
    assert shown == {"a2", "b1", "c1", "d1"}          # the FLAC copy stays in view
    assert idx.get("a1").dup_of == "a2" and idx.get("d2").dup_of == "d1"
    assert idx.stats()["tracks"] == 4 and idx.stats()["duplicates"] == 2
    assert [t.id for t in idx.copies_of("a2")] == ["a1"]
    # Showing every copy is one switch away.
    idx.hide_duplicates = False
    assert idx.list_tracks(limit=50)["total"] == 6


def test_a_favorite_copy_makes_the_shown_copy_a_favorite():
    idx = library()
    idx.set_favorite("a1", True)
    idx.mark_duplicates()
    assert "a2" in idx.favorite_ids()
    assert [t.id for t in idx.favorites()] == ["a2"]


def test_marks_are_recomputed_when_a_copy_goes_away():
    idx = library()
    idx.mark_duplicates()
    idx.delete_ids(["a2"])
    idx.mark_duplicates()
    assert idx.get("a1").dup_of == ""


def test_saved_playlists_keep_order_and_find_moved_songs():
    idx = library()
    pid = idx.create_playlist("שבת בבוקר", ["d1", "b1", "c1"])
    assert [t.id for t in idx.playlist_tracks(pid)] == ["d1", "b1", "c1"]
    assert idx.add_to_playlist(pid, ["b1", "a1"]) == 1          # b1 is already there
    idx.set_playlist_order(pid, ["a1", "c1", "d1"])               # dragged, b1 removed
    assert [t.id for t in idx.playlist_tracks(pid)] == ["a1", "c1", "d1"]
    # With copies hidden, a hidden copy plays as the shown one.
    idx.mark_duplicates()
    assert [t.id for t in idx.playlist_tracks(pid)][0] == "a2"
    # The file moved: a new id, the same name, singer and length.
    idx.delete_ids(["c1"])
    idx.upsert(track("c9", "/m/new/לכה דודי (הופעה).mp3", "לכה דודי", "אברהם פריד", 401.5))
    assert "c9" in [t.id for t in idx.playlist_tracks(pid)]
    listed = idx.playlists()
    assert listed[0]["name"] == "שבת בבוקר" and listed[0]["count"] == 3
    assert idx.playlist_by_name("  שבת   בבוקר ") == pid
    idx.rename_playlist(pid, "שבת")
    idx.delete_playlist(pid)
    assert idx.playlists() == []


def test_service_requests_and_unique_names(tmp_path):
    from hamenagen.service import PlayerService

    svc = PlayerService(tmp_path)
    svc.index.upsert_many([track("a1", "/m/a.mp3", "לכה דודי", "אברהם פריד"), track("b1", "/m/b.mp3", "ידיד נפש")])
    first = svc.playlist_create("לשבת", ["a1", "b1"])
    second = svc.playlist_create("לשבת")
    assert first["count"] == 2 and second["name"] == "לשבת (2)"
    answer = svc.handle_request("תשמיע את הרשימה לשבת")
    assert answer["understood"] == "הרשימה „לשבת”" and [t["id"] for t in answer["tracks"]] == ["a1", "b1"]
    assert svc.handle_request("לשבת")["playlist_id"] == first["id"]
    assert svc.playlist_rename(first["id"], "לשבת (2)")["name"] == "לשבת (2) (2)"
    assert svc.playlist_add(first["id"], ["b1"])["added"] == 0
    assert svc.playlist_set_order(first["id"], ["b1"])["count"] == 1
    assert svc.playlist_get(first["id"])["tracks"][0]["id"] == "b1"
    assert svc.playlist_delete(first["id"])["ok"] and len(svc.playlists()["playlists"]) == 1
