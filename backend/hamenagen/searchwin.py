"""The search window, in Edge's engine (WebView2), the way the download-from-YouTube program shows it (1.5.9).

Google shows a window of Electron's own Chromium a plainer results page than it shows Edge: no pictures, no
video cards. The download-from-YouTube program, where the same search looks right, shows Google in a
WebView2 window through pywebview. This process does the same, for the player: a window without a frame,
owned by the player's window (so it stays on top of it, goes with it when it is minimized and has no button
of its own on the taskbar), laid exactly over the place where the player shows the search.

It talks with electron/main.js in JSON lines.

  in  (stdin)   {"cmd": "open", "url": "...", "rect": [x, y, w, h]}   rect in physical screen pixels
                {"cmd": "place", "rect": [...]}  {"cmd": "hide"}  {"cmd": "nav", "action": "back"|"forward"|"reload"}
                {"cmd": "quit"}
  out (stdout)  {"event": "ready"}  {"event": "link", "url": "..."}  {"event": "escape"}
                {"event": "state", "url": "...", "loading": false}  {"event": "blocked", "site": "youtube"}
                {"event": "error", "message": "..."}

A click on a YouTube result is caught as in the download program: in the page (a click listener, the link
read from Google's /url?q=…) and when the navigation starts (WebView2's NavigationStarting, cancelled), so
the video never opens or plays here. Nothing is kept but WebView2's own profile (cookies, as in a browser).

``--selftest`` opens a page with a link to a YouTube video, clicks it, and exits 0 when the link was caught.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import threading
import time
import urllib.parse

_print_lock = threading.Lock()


def emit(event: str, **data) -> None:
    with _print_lock:
        sys.stdout.write(json.dumps({"event": event, **data}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


_WATCH = re.compile(r"(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|shorts/)|youtu\.be/)([\w-]{11})")


def youtube_link(url: str) -> str | None:
    """The one video a URL leads to (also through Google's /url?q=… redirect), or None."""
    if not url:
        return None
    try:
        u = urllib.parse.urlparse(url)
        if re.search(r"(^|\.)google\.[a-z.]+$", u.hostname or "") and u.path == "/url":
            q = urllib.parse.parse_qs(u.query)
            target = (q.get("q") or q.get("url") or [""])[0]
            return youtube_link(target)
    except ValueError:
        return None
    m = _WATCH.search(urllib.parse.unquote(url))
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


# In every page: a click on a link to a YouTube video goes to the player; Esc goes back to the player.
INJECT = r"""
(function(){
  if (window.__hamenagenHooked) return; window.__hamenagenHooked = true;
  function api(){ return window.pywebview && window.pywebview.api; }
  document.addEventListener('click', function(e){
    var a = e.target && e.target.closest ? e.target.closest('a') : null; if (!a) return;
    var href = a.href || ''; var dec = href; try { dec = decodeURIComponent(href); } catch (_) {}
    var m = dec.match(/(?:youtube\.com\/(?:watch\?(?:[^#\s"]*&)?v=|shorts\/)|youtu\.be\/)([\w-]{11})/);
    if (m && api()) { e.preventDefault(); e.stopPropagation(); api().link('https://www.youtube.com/watch?v=' + m[1]); }
  }, true);
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape' && api()) api().escape(); }, true);
})();
"""


class Api:
    """What the page may call (``window.pywebview.api``)."""

    def __init__(self, on_link, on_escape):
        self._on_link = on_link
        self._on_escape = on_escape

    def link(self, url):
        self._on_link(url)

    def escape(self):
        self._on_escape()


# ---------------------------------------------------------------- Windows
GWLP_HWNDPARENT = -8
GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


def _user32():
    return ctypes.windll.user32  # type: ignore[attr-defined]


def _dpi_aware() -> None:
    try:
        _user32().SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # per monitor, v2
    except Exception:  # noqa: BLE001 - older Windows: whatever pywebview sets
        pass


def _find_window(title: str, timeout: float = 15) -> int:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hwnd = _user32().FindWindowW(None, title)
        if hwnd:
            return hwnd
        time.sleep(0.05)
    return 0


def _own(hwnd: int, owner: int) -> None:
    u = _user32()
    set_long = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
    get_long = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
    set_long.restype = ctypes.c_ssize_t
    get_long.restype = ctypes.c_ssize_t
    style = get_long(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
    set_long(ctypes.c_void_p(hwnd), GWL_EXSTYLE, ctypes.c_ssize_t((style & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW))
    if owner:
        set_long(ctypes.c_void_p(hwnd), GWLP_HWNDPARENT, ctypes.c_ssize_t(owner))


def _place(hwnd: int, rect) -> None:
    x, y, w, h = (int(v) for v in rect)
    _user32().SetWindowPos(ctypes.c_void_p(hwnd), None, x, y, max(1, w), max(1, h), SWP_NOZORDER | SWP_NOACTIVATE)


# ---------------------------------------------------------------- the window
class SearchWindow:
    def __init__(self, owner: int, profile: str, selftest: bool = False):
        self.owner = owner
        self.profile = profile
        self.selftest = selftest
        self.title = f"hamenagen-search-{os.getpid()}"
        self.window = None
        self.hwnd = 0
        self.last_link = ("", 0.0)
        self.caught = threading.Event()

    # -- from the page
    def on_link(self, url: str) -> None:
        link = youtube_link(url) or url
        now = time.monotonic()
        if self.last_link[0] == link and now - self.last_link[1] < 2:
            return                                      # one click, several events
        self.last_link = (link, now)
        emit("link", url=link)
        self.caught.set()
        if not self.selftest:
            self.hide()

    def on_escape(self) -> None:
        emit("escape")
        self.hide()

    def on_loaded(self) -> None:
        try:
            self.window.evaluate_js(INJECT)
            url = self.window.get_current_url() or ""
            emit("state", url=url, loading=False)
            if re.search(r"(^|\.)youtube\.com/", url):
                page = self.window.evaluate_js(
                    "document.title + ' ' + (document.documentElement ? document.documentElement.innerHTML.slice(0, 20000) : '')")
                if page and re.search("netfree", str(page), re.I):
                    emit("blocked", site="youtube")
        except Exception as ex:  # noqa: BLE001
            emit("error", message=f"loaded: {ex}")

    # -- from the player
    def hide(self) -> None:
        try:
            self.window.hide()
        except Exception:  # noqa: BLE001
            pass

    def handle(self, msg: dict) -> bool:
        cmd = msg.get("cmd")
        if cmd == "open":
            if msg.get("rect"):
                _place(self.hwnd, msg["rect"])
            self.window.show()
            if msg.get("rect"):
                _place(self.hwnd, msg["rect"])
            if msg.get("url"):
                self.window.load_url(msg["url"])
        elif cmd == "place" and msg.get("rect"):
            _place(self.hwnd, msg["rect"])
        elif cmd == "hide":
            self.hide()
        elif cmd == "nav":
            action = msg.get("action")
            js = {"back": "history.back()", "forward": "history.forward()", "reload": "location.reload()"}.get(action)
            if js:
                self.window.evaluate_js(js)
        elif cmd == "quit":
            return False
        return True

    def commands(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                if not self.handle(json.loads(line)):
                    break
            except Exception as ex:  # noqa: BLE001 - a bad line must not end the window
                emit("error", message=f"{type(ex).__name__}: {ex}")
        self.window.destroy()

    def ready(self) -> None:
        """Runs once the GUI loop is up (pywebview's ``func``)."""
        self.hwnd = _find_window(self.title)
        if not self.hwnd:
            emit("error", message="the window was not found")
            self.window.destroy()
            return
        _own(self.hwnd, self.owner)
        emit("ready", hwnd=self.hwnd)
        if self.selftest:
            self._selftest()
            return
        self.commands()

    def _selftest(self) -> None:
        self.window.show()
        _place(self.hwnd, (100, 100, 900, 600))
        time.sleep(2)
        try:
            self.window.evaluate_js("document.getElementById('song').click()")
        except Exception as ex:  # noqa: BLE001
            emit("error", message=f"click: {ex}")
        ok = self.caught.wait(20)
        emit("selftest", ok=ok)
        self.window.destroy()
        os._exit(0 if ok else 1)

    def run(self) -> None:
        import webview  # pywebview, with WebView2 ("edgechromium")
        from webview.platforms import edgechromium as edge

        _dpi_aware()
        win = self

        original = edge.EdgeChrome.on_navigation_start

        def on_navigation_start(self_, sender, args):
            try:
                link = youtube_link(str(args.Uri))
                if link:
                    args.Cancel = True                    # never opens, never plays
                    win.on_link(link)
                    return
            except Exception:  # noqa: BLE001
                pass
            return original(self_, sender, args)

        edge.EdgeChrome.on_navigation_start = on_navigation_start

        html = None
        url = None
        if self.selftest:
            html = ('<html><body><h3>בדיקה</h3>'
                    '<a id="song" href="https://www.google.com/url?q=https://www.youtube.com/watch%3Fv%3Ddemo0000001&amp;sa=U">'
                    'שיר מיוטיוב</a></body></html>')
        else:
            html = "<html><body></body></html>"
        self.window = webview.create_window(
            self.title, url=url, html=html, js_api=Api(self.on_link, self.on_escape),
            width=900, height=600, frameless=True, easy_drag=False, hidden=not self.selftest,
            focus=True, shadow=False, background_color="#FFFFFF", text_select=True)
        self.window.events.loaded += self.on_loaded
        os.makedirs(self.profile, exist_ok=True)
        webview.start(self.ready, gui="edgechromium", private_mode=False, storage_path=self.profile)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--owner", type=int, default=0)
    p.add_argument("--profile", default=os.path.join(os.environ.get("HAMENAGEN_DATA_DIR", "."), "search-profile"))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if sys.platform != "win32":
        emit("error", message="WebView2 is Windows only")
        return 2
    try:
        SearchWindow(args.owner, args.profile, args.selftest).run()
    except Exception as ex:  # noqa: BLE001 - no WebView2, no pythonnet: the player uses its own window
        emit("error", message=f"{type(ex).__name__}: {ex}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
