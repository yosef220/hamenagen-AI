"""1.2: Hebrew tags in old encodings, all tag formats, covers, clean names
from file names, and reading an older library again once."""

import struct

import pytest

from hamenagen.scanner import (
    SCAN_VERSION,
    _asf_picture,
    display_folder,
    is_placeholder_title,
    scan_file,
    store_cover,
    strip_track_number,
)
from hamenagen.service import PlayerService
from hamenagen.text_normalize import repair_hebrew

mutagen = pytest.importorskip("mutagen")

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + b"\x11" * 3000 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x22" * 2000


def _mp3(path, frames=60):
    """A real (silent) MPEG-1 Layer III stream: 128 kbps, 44.1 kHz."""
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * frames)
    return path


@pytest.mark.parametrize("garbled,fixed", [
    ("øöåòä 19", "רצועה 19"),
    ("ùéø äîòìåú - Live", "שיר המעלות - Live"),
    ("ìê àìé", "לך אלי"),
    ("×ž×¢×•×– ×¦×•×¨", "מעוז צור"),
])
def test_hebrew_read_in_the_wrong_encoding_is_repaired(garbled, fixed):
    assert repair_hebrew(garbled) == fixed


@pytest.mark.parametrize("text", ["THE NO 2", "Café à l'été", "Mañana", "Grüße", "Beyoncé", "שיר רגיל", ""])
def test_real_text_is_left_alone(text):
    assert repair_hebrew(text) == text


def test_track_numbers_and_placeholders():
    assert strip_track_number("03 ואם תבואי אלי") == "ואם תבואי אלי"
    assert strip_track_number("03 - ואם תבואי אלי") == "ואם תבואי אלי"
    assert strip_track_number("3. שם") == "שם"
    assert strip_track_number("(03) שם") == "שם"
    assert strip_track_number("100 אחוז") == "100 אחוז"
    assert strip_track_number("7 דקות") == "7 דקות"
    for t in ("Track 19", "רצועה 19", "19", "Audio Track 03", "untitled"):
        assert is_placeholder_title(t), t
    assert not is_placeholder_title("לך אלי") and not is_placeholder_title("")


def test_folder_names_that_say_nothing_are_not_shown(tmp_path):
    assert display_folder(tmp_path / "אלי הרצליך" / "a.mp3") == "אלי הרצליך"
    assert display_folder(tmp_path / "Music" / "a.mp3") == ""
    assert display_folder(tmp_path / "הורדות" / "a.mp3") == ""


def test_mp3_tags_in_windows_1255_are_read_as_hebrew(tmp_path):
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1

    song = _mp3(tmp_path / "x.mp3")
    tags = ID3()
    tags.add(TIT2(encoding=0, text="ùéø äîòìåú"))   # Windows-1255 bytes declared Latin-1
    tags.add(TPE1(encoding=0, text="ìê àìé"))
    tags.add(TALB(encoding=3, text="אלבום"))
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=JPEG))
    tags.save(song)
    track = scan_file(song, covers_dir=tmp_path / "covers")
    assert (track.title, track.artist, track.album) == ("שיר המעלות", "לך אלי", "אלבום")
    assert track.duration and track.duration > 1
    assert track.cover and (tmp_path / "covers" / "src" / f"{track.cover}.jpg").read_bytes() == JPEG


def test_a_placeholder_tag_gives_way_to_the_file_name(tmp_path):
    from mutagen.id3 import ID3, TIT2

    song = _mp3(tmp_path / "03 ואם תבואי אלי.mp3")
    tags = ID3()
    tags.add(TIT2(encoding=0, text="øöåòä 19"))
    tags.save(song)
    assert scan_file(song).title == "ואם תבואי אלי"


def test_a_folder_picture_is_the_cover_when_the_file_has_none(tmp_path):
    album = tmp_path / "אלי הרצליך"
    album.mkdir()
    _mp3(album / "המלאך.mp3")
    (album / "Folder.jpg").write_bytes(JPEG)
    track = scan_file(album / "המלאך.mp3", covers_dir=tmp_path / "covers", folder_cache={})
    assert track.cover and track.title == "המלאך"


def test_covers_are_kept_once_by_content(tmp_path):
    a = store_cover(JPEG, tmp_path)
    assert a == store_cover(JPEG, tmp_path) and len(list((tmp_path / "src").iterdir())) == 1
    png = store_cover(PNG, tmp_path)
    assert png and png != a and (tmp_path / "src" / f"{png}.png").exists()
    assert store_cover(b"not a picture", tmp_path) == ""
    # Once the app has made its small copy, the original is not written again.
    (tmp_path / f"{a}.jpg").write_bytes(b"small")
    (tmp_path / "src" / f"{a}.jpg").unlink()
    assert store_cover(JPEG, tmp_path) == a and not (tmp_path / "src" / f"{a}.jpg").exists()


def test_wma_picture_values_are_parsed():
    mime = "image/jpeg".encode("utf-16-le") + b"\x00\x00"
    desc = "".encode("utf-16-le") + b"\x00\x00"
    blob = bytes([3]) + struct.pack("<I", len(JPEG)) + mime + desc + JPEG
    assert _asf_picture(blob) == (3, JPEG)
    assert _asf_picture(b"\x03") is None


def test_flac_pictures_and_vorbis_tags(tmp_path):
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    from mutagen.flac import FLAC, Picture

    path = tmp_path / "song.flac"
    sf.write(str(path), np.zeros(44100 * 2, dtype="float32"), 44100)
    audio = FLAC(path)
    audio["title"] = "אדון עולם"
    audio["artist"] = "מקהלה"
    pic = Picture()
    pic.type, pic.mime, pic.data = 3, "image/png", PNG
    audio.add_picture(pic)
    audio.save()
    track = scan_file(path, covers_dir=tmp_path / "covers")
    assert (track.title, track.artist) == ("אדון עולם", "מקהלה") and track.cover


def test_full_scan_rereads_once_after_an_upgrade(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    for name in ("ישי ריבו - לך אלי.mp3", "03 ואם תבואי אלי.mp3"):
        _mp3(music / name, frames=900)  # 23 s, 375 KB: a song, not a notification sound
    service = PlayerService(data_dir=tmp_path / "data")
    service.settings.use_embeddings = False
    service.classifier.embedding = None
    monkeypatch.setattr(service, "_roots", lambda: [str(music)])
    assert service.rescan()["added"] == 2
    assert service.index.get_meta("scan_version") == SCAN_VERSION
    assert service.rescan()["updated"] == 0
    service.index.set_meta("scan_version", "1")   # as an older version left it
    assert service.rescan()["updated"] == 2
    assert service.rescan()["updated"] == 0
    titles = {t.title for t in service.index.all_tracks()}
    assert titles == {"לך אלי", "ואם תבואי אלי"}
    service.close()
