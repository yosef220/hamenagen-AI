"""The smart update end to end: two builds of the app, their parts (made by
the real packaging scripts), the plan, a checked download, and the swap.

The swap itself is the PowerShell script on Windows (electron/update-apply.ps1,
exercised by the release workflow); here a few lines of Python do the same
moves, to check that the plan and the staged files are right."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from hamenagen.smart_update import SmartUpdater, content_hash, sha256_file

REPO = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is needed to run scripts/parts.js")


def build(folder: Path, *, version: str, backend: str, asar: bytes, exe: bytes) -> Path:
    """A tiny app laid out like win-unpacked, with its parts.json."""
    files = {
        "Hamenagen.exe": exe,                       # the version is stamped into it on every build
        "ffmpeg.dll": b"chromium media",
        "locales/he.pak": b"hebrew",
        "resources/app.asar": asar,
        "resources/backend/hamenagen/__init__.py": backend.encode(),
        "resources/python/python.exe": b"python",
        "resources/python/Lib/site-packages/yt_dlp/__init__.py": b"yt-dlp",
        "resources/models/e5/model.onnx": b"m" * 50_000,
        "resources/ffmpeg/ffmpeg.exe": b"ffmpeg build " + version.encode(),   # rebuilt, same version
        "resources/ffmpeg/VERSION.txt": b"ffmpeg version n7.1.2-12-gabcdef-20261101",
        "resources/ffmpeg/LICENSE.txt": b"LGPL",
        # Left by the build's checks, which run the packaged core: never part
        # of a fingerprint or of a part's ZIP.
        "resources/backend/hamenagen/__pycache__/__init__.cpython-311.pyc": b"cache " + version.encode(),
        "resources/python/Lib/site-packages/yt_dlp/__pycache__/__init__.cpython-311.pyc": b"cache",
    }
    for rel, data in files.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    script = (
        "const p = require(process.argv[1]);"
        "const m = p.describeParts({ appOutDir: process.argv[2], version: process.argv[3], edition: 'offline',"
        " electronVersion: '39.0.0', fuses: { runAsNode: false }, iconFile: '' });"
        "require('fs').writeFileSync(require('path').join(process.argv[2], 'resources', 'parts.json'), JSON.stringify(m));"
    )
    subprocess.run([NODE, "-e", script, str(REPO / "scripts" / "parts.js"), str(folder), version], check=True)
    return folder


def release_entry(new: Path, parts_dir: Path, version: str) -> dict:
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_parts.py"), str(new), str(parts_dir)], check=True)
    for z in parts_dir.glob("*.zip"):   # the caches stay out of every ZIP
        with zipfile.ZipFile(z) as zf:
            assert not [n for n in zf.namelist() if "__pycache__" in n or n.endswith(".pyc")], z.name
    manifest = json.loads((parts_dir / "parts-offline.json").read_text(encoding="utf-8"))
    for part in manifest["parts"].values():
        z = parts_dir / part["file"]
        part.update(url=z.as_uri(), size=z.stat().st_size, sha256=sha256_file(z))
    return {"latest": version, "newer": True, "parts": manifest}


def swap(plan_path: Path) -> None:
    """What update-apply.ps1 does, without the waiting and the rollback."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    backup = Path(plan["work"]) / "backup"
    backup.mkdir(parents=True, exist_ok=True)
    for part in plan["parts"]:
        base = Path(plan["root"] if part["kind"] == "root" else plan["resources"])
        for entry in part["old"]:
            if (base / entry).exists():
                shutil.move(str(base / entry), str(backup / f"{part['name']}__{entry}"))
        for entry in part["new"]:
            shutil.move(str(Path(part["staging"]) / entry), str(base / entry))
    shutil.copyfile(plan["parts_json"], Path(plan["resources"]) / "parts.json")
    Path(plan["result"]).write_text(json.dumps({"ok": True, "version": plan["version"]}), encoding="utf-8")


def test_the_hash_is_the_same_in_javascript_and_python(tmp_path):
    app = build(tmp_path / "app", version="1.3.0", backend="v1", asar=b"asar-1", exe=b"exe 1.3.0")
    manifest = json.loads((app / "resources" / "parts.json").read_text(encoding="utf-8"))
    res = app / "resources"
    assert manifest["parts"]["backend"]["hash"] == content_hash(res, ["backend"])
    assert manifest["parts"]["python"]["hash"] == content_hash(res, ["python"])
    assert manifest["parts"]["app"]["hash"] == content_hash(res, ["app.asar"])
    assert manifest["parts"]["runtime"]["fingerprint"] and manifest["parts"]["ffmpeg"]["fingerprint"]
    assert set(manifest["parts"]["runtime"]["entries"]) == {"Hamenagen.exe", "ffmpeg.dll", "locales"}


def test_only_the_changed_parts_are_downloaded_and_swapped(tmp_path):
    installed = build(tmp_path / "installed", version="1.3.0", backend="v1", asar=b"asar-1", exe=b"exe 1.3.0")
    new = build(tmp_path / "new", version="1.3.1", backend="v2", asar=b"asar-2", exe=b"exe 1.3.1")
    release = release_entry(new, tmp_path / "parts", "1.3.1")
    data = tmp_path / "data"
    updater = SmartUpdater(data, installed / "resources")

    plan = updater.plan(release)
    # The model, Python, the runtime (only its version stamp changed) and
    # ffmpeg (rebuilt, same version) stay; the core and the app change.
    assert plan["possible"] and sorted(plan["changed"]) == ["app", "backend"]
    assert plan["download"] < plan["full"] / 10

    events = []
    out = updater.download(release, events.append)
    assert out["ok"], out
    assert events[-1]["status"] == "ready" and events[-1]["done"] == plan["download"]
    swap(Path(out["plan"]))
    res = installed / "resources"
    assert (res / "backend" / "hamenagen" / "__init__.py").read_text() == "v2"
    assert (res / "app.asar").read_bytes() == b"asar-2"
    assert (res / "models" / "e5" / "model.onnx").exists()            # never downloaded again
    assert (installed / "Hamenagen.exe").read_bytes() == b"exe 1.3.0"  # kept: same runtime
    assert json.loads((res / "parts.json").read_text())["version"] == "1.3.1"
    assert updater.result()["ok"] and not (data / "update" / "staging").exists()
    # Now up to date with that release.
    again = SmartUpdater(data, res).plan(release)
    assert again["possible"] and again["changed"] == []


def test_a_part_that_changed_after_its_fingerprint_stops_the_build(tmp_path):
    # As in 1.3.0, when the build's checks wrote into the package after the
    # fingerprints were taken: the app would refuse such a part, so the
    # build refuses to publish it.
    new = build(tmp_path / "new", version="1.3.1", backend="v2", asar=b"asar-2", exe=b"exe 1.3.1")
    (new / "resources" / "backend" / "hamenagen" / "written-later.txt").write_text("x")
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "make_parts.py"), str(new), str(tmp_path / "parts")],
                         capture_output=True, text=True)
    assert out.returncode == 1 and "backend" in out.stderr and "python" not in out.stderr


def test_the_packaging_hook_removes_python_caches(tmp_path):
    app = build(tmp_path / "app", version="1.3.0", backend="v1", asar=b"asar-1", exe=b"exe 1.3.0")
    script = "const p = require(process.argv[1]); console.log(p.removeCaches(process.argv[2]));"
    out = subprocess.run([NODE, "-e", script, str(REPO / "scripts" / "parts.js"), str(app / "resources")],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "2"
    assert not list((app / "resources").rglob("__pycache__")) and not list((app / "resources").rglob("*.pyc"))


def test_a_copy_of_1_3_0_accepts_the_new_parts(tmp_path, monkeypatch):
    # 1.3.0 counts every file it unpacks, caches included; the parts hold
    # none, so its check agrees with the fingerprint.
    import hamenagen.smart_update as su
    monkeypatch.setattr(su, "is_cache", lambda rel: False)
    installed = build(tmp_path / "installed", version="1.3.0", backend="v1", asar=b"asar-1", exe=b"exe 1.3.0")
    new = build(tmp_path / "new", version="1.3.1", backend="v2", asar=b"asar-2", exe=b"exe 1.3.1")
    release = release_entry(new, tmp_path / "parts", "1.3.1")
    out = SmartUpdater(tmp_path / "data", installed / "resources").download(release)
    assert out["ok"], out


def test_a_damaged_download_is_refused(tmp_path):
    installed = build(tmp_path / "installed", version="1.3.0", backend="v1", asar=b"asar-1", exe=b"exe 1.3.0")
    new = build(tmp_path / "new", version="1.3.1", backend="v2", asar=b"asar-2", exe=b"exe 1.3.1")
    release = release_entry(new, tmp_path / "parts", "1.3.1")
    release["parts"]["parts"]["backend"]["sha256"] = "0" * 64
    out = SmartUpdater(tmp_path / "data", installed / "resources").download(release)
    assert not out["ok"] and "damaged" in out["message"]
    assert not (tmp_path / "data" / "update" / "plan.json").exists()


def test_when_a_smart_update_is_not_possible(tmp_path):
    installed = build(tmp_path / "installed", version="1.3.0", backend="v1", asar=b"asar-1", exe=b"exe 1.3.0")
    updater = SmartUpdater(tmp_path / "data", installed / "resources")
    assert updater.plan({"latest": "1.3.1", "newer": True})["reason"] == "no_parts_in_release"
    assert updater.plan({"latest": "1.3.0", "newer": False})["reason"] == "up_to_date"
    # A copy from before 1.3 has no parts.json: the full download it is.
    assert SmartUpdater(tmp_path / "data", None).plan({"latest": "1.3.1", "newer": True, "parts": {}})["reason"] \
        == "no_parts_here"
    other = {"latest": "1.3.1", "newer": True, "parts": {"edition": "setup", "parts": {"x": {}}}}
    assert updater.plan(other)["reason"] == "other_edition"


def test_a_swap_that_never_ran_is_reported_with_its_log(tmp_path):
    """1.4.0: the old core held its folder, the swap waited and the listener
    started the app again; the same update was then offered over and over."""
    import json as _json
    import os as _os
    import time as _time

    from hamenagen.smart_update import SmartUpdater

    updater = SmartUpdater(tmp_path / "data", tmp_path / "inst" / "resources")
    updater.work.mkdir(parents=True, exist_ok=True)
    plan = updater.work / "plan.json"
    plan.write_text(_json.dumps({"version": "1.4.1"}), encoding="utf-8")
    (updater.work / "apply.log").write_text("waiting for the player to close\ncannot move backend: in use\n",
                                            encoding="utf-8")
    assert updater.result() is None                      # just written: it may still be running
    old = _time.time() - updater.STALE_PLAN_SECONDS - 5
    _os.utime(plan, (old, old))
    out = updater.result()
    assert out["ok"] is False and out["stale"] and out["version"] == "1.4.1" and "in use" in out["log"]
    assert not plan.exists() and updater.result() is None   # once


def test_a_failed_swap_carries_its_log(tmp_path):
    import json as _json

    from hamenagen.smart_update import SmartUpdater

    updater = SmartUpdater(tmp_path / "data", tmp_path / "inst" / "resources")
    updater.work.mkdir(parents=True, exist_ok=True)
    (updater.work / "result.json").write_text(_json.dumps({"ok": False, "version": "1.4.1", "error": "x"}))
    (updater.work / "apply.log").write_text("part backend\nfailed: x\n", encoding="utf-8")
    out = updater.result()
    assert out["ok"] is False and "failed: x" in out["log"]
