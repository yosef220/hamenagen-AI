"""1.6: playlists in from other players and Google Takeout, and out as M3U8."""

import zipfile

from hamenagen import playlist_io as pio
from hamenagen.models import Track
from hamenagen.service import PlayerService


def _service(tmp_path):
    music = tmp_path / "music"
    (music / "שבת").mkdir(parents=True)
    songs = [
        Track(id="a", path=str(music / "שבת" / "ישי ריבו - מנוחה ושמחה.mp3"), title="מנוחה ושמחה", artist="ישי ריבו",
              duration=200),
        Track(id="b", path=str(music / "אברהם פריד - אבינו מלכנו [dQw4w9WgXcQ].mp3"), title="אבינו מלכנו",
              artist="אברהם פריד", duration=300),
        Track(id="c", path=str(music / "שיר.mp3"), title="ירושלים של זהב", artist="נעמי שמר", duration=250),
    ]
    service = PlayerService(data_dir=tmp_path / "data")
    for t in songs:
        service.index.upsert(t)
    return service, music


def test_m3u_and_pls_are_read():
    m3u = "#EXTM3U\n#EXTINF:200,ישי ריבו - מנוחה ושמחה\nC:\\Music\\שבת\\a.mp3\n\n#EXTINF:-1,שיר\nrel/b.mp3\n"
    rows = pio.parse_m3u(m3u)
    assert (rows[0].artist, rows[0].title, rows[0].duration) == ("ישי ריבו", "מנוחה ושמחה", 200.0)
    assert rows[0].path == "C:\\Music\\שבת\\a.mp3" and rows[1].path == "rel/b.mp3" and rows[1].duration is None
    pls = "[playlist]\nFile1=/m/x.mp3\nTitle1=זמר - שיר\nLength1=180\nNumberOfEntries=1\n"
    (e,) = pio.parse_pls(pls)
    assert (e.path, e.artist, e.title, e.duration) == ("/m/x.mp3", "זמר", "שיר", 180.0)


def test_csv_from_another_player_and_from_takeout():
    exportify = 'Track Name,Artist Name(s),Album Name\n"ירושלים של זהב","נעמי שמר, אחר",אלבום\n'
    (e,) = pio.parse_csv(exportify)
    assert (e.title, e.artist) == ("ירושלים של זהב", "נעמי שמר")
    takeout_old = "Playlist Id,Channel Id,Time Created\nPL1,UC1,2024\n\nVideo Id,Time Added\ndQw4w9WgXcQ,2024\n"
    assert [x.video_id for x in pio.parse_csv(takeout_old)] == ["dQw4w9WgXcQ"]
    takeout_new = "Video ID,Playlist Video Creation Timestamp\ndQw4w9WgXcQ,2025-01-01T00:00:00+00:00\n"
    assert [x.video_id for x in pio.parse_csv(takeout_new)] == ["dQw4w9WgXcQ"]


def test_import_matches_by_path_file_name_video_id_and_name(tmp_path):
    service, music = _service(tmp_path)
    try:
        pl = tmp_path / "שבת בבוקר.m3u8"
        pl.write_text(
            "#EXTM3U\n"
            "music/שבת/ישי ריבו - מנוחה ושמחה.mp3\n"          # relative to the playlist
            "D:\\old\\אברהם פריד - אבינו מלכנו [dQw4w9WgXcQ].mp3\n"  # moved: by its name
            "#EXTINF:250,נעמי שמר - ירושלים של זהב\nE:\\gone\\x.mp3\n"  # by name and singer
            "#EXTINF:100,מישהו - שיר שאין\nE:\\gone\\y.mp3\n",
            encoding="utf-8")
        r = service.playlist_import(str(pl))
        assert r["ok"] and r["found"] == 3 and r["missing"] == 1
        made = r["playlists"][0]
        assert made["name"] == "שבת בבוקר"
        assert [t["id"] for t in service.playlist_get(made["id"])["tracks"]] == ["a", "b", "c"]
    finally:
        service.close()


def test_takeout_zip_makes_one_playlist_each(tmp_path):
    service, _ = _service(tmp_path)
    try:
        z = tmp_path / "takeout.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("Takeout/YouTube and YouTube Music/playlists/לחתונה-videos.csv",
                       "Video ID,Playlist Video Creation Timestamp\ndQw4w9WgXcQ,2025\nAAAAAAAAAAA,2025\n")
            f.writestr("Takeout/YouTube and YouTube Music/playlists/ריקה-videos.csv",
                       "Video ID,Playlist Video Creation Timestamp\nBBBBBBBBBBB,2025\n")
            f.writestr("Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv",
                       "Channel Id,Channel Url,Channel Title\n")
        r = service.playlist_import(str(z))
        assert [p["name"] for p in r["playlists"]] == ["לחתונה"]
        assert r["found"] == 1 and r["missing"] == 2 and r["empty"] == ["ריקה"]
    finally:
        service.close()


def test_nothing_found_creates_nothing(tmp_path):
    service, _ = _service(tmp_path)
    try:
        f = tmp_path / "x.m3u"
        f.write_text("#EXTINF:100,מישהו - אין\nE:\\x.mp3\n", encoding="utf-8")
        r = service.playlist_import(str(f))
        assert not r["ok"] and service.playlists()["playlists"] == []
        empty = tmp_path / "empty.csv"
        empty.write_text("a,b\n1,2\n", encoding="utf-8")
        assert not service.playlist_import(str(empty))["ok"]
    finally:
        service.close()


def test_export_writes_paths_relative_to_the_music(tmp_path):
    service, music = _service(tmp_path)
    try:
        pid = service.playlist_create("שבת: בבוקר", ["a", "c"])["id"]
        r = service.playlist_export(pid, str(music))
        assert r["ok"] and r["path"].endswith("שבת בבוקר.m3u8")   # ":" cannot be in a file name
        lines = (music / "שבת בבוקר.m3u8").read_text(encoding="utf-8").splitlines()
        assert lines[0] == "#EXTM3U"
        assert lines[1] == "#EXTINF:200,ישי ריבו - מנוחה ושמחה"
        assert lines[2].replace("\\", "/") == "שבת/ישי ריבו - מנוחה ושמחה.mp3"
        # And it reads back as the same playlist.
        again = service.playlist_import(r["path"])
        assert again["found"] == 2 and again["missing"] == 0
    finally:
        service.close()
