"""1.7: yt-dlp gets a JavaScript engine for YouTube's challenges, and an
engine update brings the challenge scripts the new yt-dlp asks for."""

import io
import zipfile

from hamenagen import ytdlp_runner as yr


def test_the_bundled_quickjs_comes_first(tmp_path, monkeypatch):
    (tmp_path / "qjs.exe").write_bytes(b"MZ")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    assert yr.find_js_runtime(tmp_path) == ("quickjs", str(tmp_path / "qjs.exe"))
    # Without one in the app: deno, then node, on the computer.
    assert yr.find_js_runtime(tmp_path / "none") == ("deno", "/usr/bin/deno")
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert yr.find_js_runtime(None) is None


def test_every_run_names_the_engine():
    runner = yr.YtDlpRunner(js_runtime=("quickjs", r"C:\app\resources\js\qjs.exe"))
    cmd = runner.command(["--version"])
    i = cmd.index("--js-runtimes")
    assert cmd[i + 1] == r"quickjs:C:\app\resources\js\qjs.exe"
    assert "--js-runtimes" not in yr.YtDlpRunner().command(["--version"])


def test_a_client_profile_with_more_than_the_client_is_passed_whole():
    runner = yr.YtDlpRunner()
    cmd = runner.command([], client="player_client=tv,web_embedded;skip=hls")
    assert cmd[cmd.index("--extractor-args") + 1] == "youtube:player_client=tv,web_embedded;skip=hls"
    cmd = runner.command([], client="android_vr,android,web")
    assert cmd[cmd.index("--extractor-args") + 1] == "youtube:player_client=android_vr,android,web"


def test_the_scripts_version_a_wheel_pins():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("yt_dlp-2026.11.1.dist-info/METADATA",
                   "Name: yt-dlp\nRequires-Dist: yt-dlp-ejs==0.9.1; extra == 'default'\n")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        assert yr._ejs_requirement(z) == "0.9.1"


def test_the_data_folders_scripts_win(tmp_path):
    (tmp_path / "yt_dlp_ejs").mkdir()
    (tmp_path / "yt_dlp_ejs" / "__init__.py").write_text("")
    (tmp_path / "yt_dlp_ejs" / "_version.py").write_text("__version__ = version = '0.9.1'\n")
    assert yr.YtDlpRunner(engine_dir=tmp_path).ejs_version() == "0.9.1"
