"""The WebView2 search window's link reading (the window itself is checked on Windows, in CI)."""

from hamenagen import searchwin


def test_youtube_links_are_read_like_the_download_program_reads_them():
    yl = searchwin.youtube_link
    assert yl("https://www.youtube.com/watch?v=MhE6kA0TT9k&list=RDMhE6kA0TT9k") == "https://www.youtube.com/watch?v=MhE6kA0TT9k"
    assert yl("https://www.google.com/url?q=https://www.youtube.com/watch%3Fv%3DMhE6kA0TT9k&sa=U") == \
        "https://www.youtube.com/watch?v=MhE6kA0TT9k"
    assert yl("https://youtu.be/MhE6kA0TT9k?t=3") == "https://www.youtube.com/watch?v=MhE6kA0TT9k"
    assert yl("https://www.youtube.com/shorts/MhE6kA0TT9k") == "https://www.youtube.com/watch?v=MhE6kA0TT9k"
    assert yl("https://www.youtube.com/results?search_query=x") is None
    assert yl("https://www.google.com/search?q=x") is None
    assert yl("") is None


def test_the_injected_script_catches_clicks_and_esc():
    assert "pywebview.api" in searchwin.INJECT and "Escape" in searchwin.INJECT and "addEventListener('click'" in searchwin.INJECT


def test_elsewhere_than_windows_it_says_so(capsys):
    import sys

    if sys.platform == "win32":
        return
    assert searchwin.main(["--profile", "x"]) == 2
    assert '"event": "error"' in capsys.readouterr().out
