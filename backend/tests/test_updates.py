"""Tests for versioning, the updater diff, and the offline pack (spec §6.2, §14)."""

import json

import pytest

from hamenagen.offline_pack import PackError, build_pack, find_packs, install_pack, read_manifest
from hamenagen.updater import Updater, diff_versions
from hamenagen.versioning import compare, is_newer, version_tuple


# -- versioning -----------------------------------------------------------
def test_version_compare():
    assert compare("0.1.0", "0.2.0") == -1
    assert compare("0.2.0", "0.2.0") == 0
    assert compare("1.10.0", "1.9.0") == 1
    assert is_newer("2026.8.1", "2024.1.0")
    assert version_tuple("v0.1") == (0, 1)


# -- updater diff ---------------------------------------------------------
def test_diff_versions_offers_newer_and_unknown():
    current = {"app": "0.1.0", "ytdlp": None, "lexicon": "2", "model": None}
    manifest = {
        "app": {"version": "0.1.0"},                      # same -> no update
        "ytdlp": {"version": "2026.8.1"},                 # unknown current -> offer
        "lexicon": {"version": "3", "url": "http://x/l"},  # newer -> offer
    }
    ups = {u["component"]: u for u in diff_versions(current, manifest)}
    assert "app" not in ups
    assert ups["ytdlp"]["action"] == "auto"
    assert ups["lexicon"]["latest"] == "3"
    assert ups["lexicon"]["url"] == "http://x/l"


def test_check_offline_is_graceful(tmp_path):
    up = Updater("http://127.0.0.1:9/none", tmp_path)
    result = up.check()
    assert result["online"] is False
    assert result["updates"] == []


# -- offline pack ---------------------------------------------------------
def test_build_and_install_pack_roundtrip(tmp_path):
    # Two source files to bundle.
    (tmp_path / "model.bin").write_bytes(b"pretend-model-weights")
    (tmp_path / "topics.json").write_text('{"שבת": ["מנוחה"]}', encoding="utf-8")

    pack = tmp_path / "assets.pack"
    build_pack(
        pack,
        [
            ("embed-he-mini", "model", tmp_path / "model.bin"),
            ("topics-lexicon", "lexicon", tmp_path / "topics.json"),
        ],
    )
    assert pack.exists()
    assert find_packs(tmp_path) == [pack]

    manifest = read_manifest(pack)
    assert manifest["pack_format"] == 1
    assert len(manifest["components"]) == 2

    dest = tmp_path / "install"
    result = install_pack(pack, dest)
    assert result["ok"] and result["count"] == 2
    assert (dest / "model" / "model.bin").read_bytes() == b"pretend-model-weights"
    # Installation is recorded.
    marker = json.loads((dest / "installed_packs.json").read_text(encoding="utf-8"))
    assert marker[0]["pack"] == "assets.pack"


def test_corrupt_pack_fails_integrity(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"hello")
    pack = tmp_path / "bad.pack"
    build_pack(pack, [("a", "bin", tmp_path / "a.bin")])

    # Tamper: rewrite the manifest with a wrong sha256.
    import zipfile

    manifest = read_manifest(pack)
    manifest["components"][0]["sha256"] = "0" * 64
    # Rebuild the zip with the tampered manifest.
    import shutil

    tampered = tmp_path / "tampered.pack"
    with zipfile.ZipFile(pack) as zin, zipfile.ZipFile(tampered, "w") as zout:
        for item in zin.namelist():
            if item == "manifest.json":
                zout.writestr(item, json.dumps(manifest))
            else:
                zout.writestr(item, zin.read(item))

    with pytest.raises(PackError):
        install_pack(tampered, tmp_path / "out")
