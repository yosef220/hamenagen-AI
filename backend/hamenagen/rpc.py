"""Line-delimited JSON-RPC bridge over stdio (Electron ↔ Python).

The Electron main process spawns the core and exchanges newline-delimited
JSON messages with it:

    request : {"id": 1, "method": "handle_request", "params": {"text": "..."}}
    response: {"id": 1, "ok": true, "result": {...}}
    error   : {"id": 1, "ok": false, "error": "..."}
    event   : {"event": "scan_progress", ...}            (no id, pushed)

Keeping the transport this simple (no HTTP server, no ports) keeps the app
portable and avoids opening any network socket on the user's machine.

Quick requests are answered inline, in order. Requests that touch the network
or take long (search, download, radio, updates) run on a small worker pool and
answer when done — responses carry their id, so order does not matter — and
library-wide jobs (scan, model install, reclassify) run on their own thread
and report through events. The window therefore never waits on the network.
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import network
from .fetcher import SearchResult, clean_video_title
from .service import PlayerService

# Methods answered on the worker pool rather than inline.
_SLOW = {
    "online_search", "online_download", "online_link", "radio_list", "check_updates", "apply_update",
    "install_offline_pack", "rescan", "reclassify", "vocal_status", "lookup_details", "apply_details",
    "online_set", "listen_prepare",
}


def _shown(r: SearchResult, **extra) -> dict:
    """A result for the interface, with a clean name to show
    ("אלי הרצליך - המלאך" rather than the whole video title)."""
    artist, song = clean_video_title(r.title, r.channel or r.uploader)
    shown = f"{artist} - {song}" if artist and song and artist != (r.channel or r.uploader) else song
    return dict(r.__dict__, display=shown or r.title, **extra)


def _result_from(r: dict) -> SearchResult:
    """A search result as the interface sends it back."""
    return SearchResult(
        source=r.get("source", "youtube"), id=r.get("id", ""), title=r.get("title", ""), url=r.get("url", ""),
        uploader=r.get("uploader", ""), duration=r.get("duration"), upload_date=r.get("upload_date"),
        channel=r.get("channel", ""), channel_id=r.get("channel_id", ""), channel_url=r.get("channel_url", ""),
        thumbnail=r.get("thumbnail", ""),
    )


class RpcServer:
    def __init__(self, service: PlayerService | None = None) -> None:
        self.service = service or PlayerService()
        self.fetcher = self.service.fetcher
        self._out = sys.stdout  # set for real in serve(); used by progress hooks
        self._write_lock = threading.Lock()  # serialize stdout across threads
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rpc")
        self._jobs: dict[str, bool] = {}
        self._jobs_lock = threading.Lock()

    def _write(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self._write_lock:
            self._out.write(line)
            self._out.flush()

    def _emit(self, event: str, payload: dict) -> None:
        """Push an out-of-band notification (no id) to the client, e.g. progress."""
        self._write({"event": event, **payload})

    # Each handler takes a params dict and returns a JSON-serialisable value.
    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handler = getattr(self, f"rpc_{method}", None)
        if handler is None:
            raise ValueError(f"unknown method: {method}")
        return handler(params)

    def _answer(self, rid, method: str, params: dict) -> None:
        try:
            out = {"id": rid, "ok": True, "result": self._dispatch(method, params)}
        except Exception as exc:  # noqa: BLE001 - report all errors to caller
            out = {"id": rid, "ok": False, "error": str(exc), "trace": traceback.format_exc()}
        self._write(out)

    def _start_job(self, name: str, work, done_event: str) -> dict:
        """Run ``work()`` on its own thread once at a time; emit its result."""
        with self._jobs_lock:
            if self._jobs.get(name):
                return {"started": False, "reason": "already running"}
            self._jobs[name] = True

        def runner():
            try:
                self._emit(done_event, work() or {})
            except Exception as exc:  # noqa: BLE001
                self._emit(done_event, {"error": str(exc)})
            finally:
                with self._jobs_lock:
                    self._jobs[name] = False

        threading.Thread(target=runner, name=f"job-{name}", daemon=True).start()
        return {"started": True}

    # -- general -----------------------------------------------------------
    def rpc_ping(self, params):
        return {"pong": True}

    def rpc_app_info(self, params):
        return self.service.app_info()

    def rpc_today(self, params):
        return self.service.today()

    def rpc_shabbat_status(self, params):
        return self.service.shabbat_status()

    def rpc_opening_suggestion(self, params):
        return self.service.opening_suggestion()

    # -- playing -----------------------------------------------------------
    def rpc_handle_request(self, params):
        return self.service.handle_request(params.get("text", ""))

    def rpc_playlist(self, params):
        return self.service.playlist(
            params.get("kind", "random"),
            topic=params.get("topic"),
            minutes=params.get("minutes"),
            limit=params.get("limit"),
        )

    def rpc_set_favorite(self, params):
        return self.service.set_favorite(params.get("id", ""), bool(params.get("on", True)))

    def rpc_record_play(self, params):
        return self.service.record_play(params.get("id", ""))

    def rpc_track_lyrics(self, params):
        return self.service.track_lyrics(params.get("id", ""))

    # -- library -----------------------------------------------------------
    def rpc_library_overview(self, params):
        return self.service.library_overview()

    # -- saved playlists and copies -------------------------------------------
    def rpc_playlists(self, params):
        return self.service.playlists()

    def rpc_playlist_get(self, params):
        return self.service.playlist_get(params.get("id", 0))

    def rpc_playlist_create(self, params):
        return self.service.playlist_create(params.get("name", ""), params.get("track_ids") or [])

    def rpc_playlist_rename(self, params):
        return self.service.playlist_rename(params.get("id", 0), params.get("name", ""))

    def rpc_playlist_delete(self, params):
        return self.service.playlist_delete(params.get("id", 0))

    def rpc_playlist_add(self, params):
        return self.service.playlist_add(params.get("id", 0), params.get("track_ids") or [])

    def rpc_playlist_set_order(self, params):
        return self.service.playlist_set_order(params.get("id", 0), params.get("track_ids") or [])

    def rpc_track_copies(self, params):
        return self.service.track_copies(params.get("id", ""))

    def rpc_list_tracks(self, params):
        return self.service.list_tracks(**params)

    def rpc_topics(self, params):
        return self.service.topics()

    def rpc_rescan(self, params):
        return self.service.rescan(params.get("roots"))

    def rpc_rescan_async(self, params):
        """Scan the library on a background thread so the UI never freezes.

        Emits ``scan_progress`` while walking and ``scan_done`` at the end.
        """
        roots = params.get("roots")

        def work():
            self.service.scanning = True
            self._emit("scan_progress", {"files": 0, "added": 0, "updated": 0})
            try:
                return self.service.rescan(roots, on_progress=lambda p: self._emit("scan_progress", p))
            finally:
                self.service.scanning = False
                # New songs are listened to for singing without instruments.
                self.rpc_analyze_vocal_async({})

        return self._start_job("scan", work, "scan_done")

    # -- the listener's corrections ------------------------------------------
    def rpc_set_track_topic(self, params):
        return self.service.set_track_topic(params.get("id", ""), params.get("topic"))

    def rpc_set_track_vocal(self, params):
        return self.service.set_track_vocal(params.get("id", ""), params.get("value"))

    def rpc_confirm_vocal(self, params):
        return self.service.confirm_vocal(list(params.get("ids") or []), bool(params.get("value", True)))

    # -- listening for a cappella songs ------------------------------------------
    def rpc_vocal_status(self, params):
        return self.service.vocal_status()

    def rpc_vocal_review(self, params):
        return self.service.vocal_review(int(params.get("limit", 300)))

    def rpc_analyze_vocal_async(self, params):
        """Listen to the songs not heard yet, on a background thread.
        Emits ``vocal_progress`` and ``vocal_done``."""
        listen, rhythm = self.service._listening_plan()
        if not listen and not rhythm:
            available = self.service.vocal.status().get("available")
            return {"started": False, "reason": "disabled" if available else "unavailable"}

        def work():
            return self.service.analyze_vocal(on_progress=lambda p: self._emit("vocal_progress", p))

        return self._start_job("vocal", work, "vocal_done")

    def rpc_stop_vocal(self, params):
        self.service.vocal_stop = True
        return {"stopping": self.service.vocal_running}

    # -- the AI model ------------------------------------------------------
    def rpc_classifier_status(self, params):
        return self.service.classifier_status()

    def rpc_install_model_async(self, params):
        """Get the AI model ready on a background thread (first-run install).

        Emits ``model_install`` with status "downloading" | "done" | "error".
        Loading reads the bundled copy in the offline edition, or downloads it
        once otherwise.
        """
        status = self.service.classifier_status()
        if not status.get("enabled"):
            return {"started": False, "reason": "embeddings disabled"}
        if status.get("loaded"):
            return {"started": False, "reason": "already installed"}

        def work():
            self._emit("model_install", {"status": "loading" if status.get("cached") else "downloading"})
            backend = self.service.classifier.embedding
            if backend is not None:
                def progress(p: dict) -> None:
                    pct = round(p["downloaded"] * 100 / p["total"], 1) if p.get("total") else None
                    self._emit("model_install", {"status": "downloading", "percent": pct, "file": p.get("file")})
                backend.on_download = progress
            result = self.service.install_model()
            return {"status": "done" if result.get("ok") else "error", **result}

        return self._start_job("model", work, "model_install")

    def rpc_reclassify(self, params):
        return self.service.reclassify_all()

    def rpc_reclassify_async(self, params):
        def work():
            return self.service.reclassify_all(on_progress=lambda p: self._emit("reclassify_progress", p))

        return self._start_job("reclassify", work, "reclassify_done")

    # -- settings ----------------------------------------------------------
    def rpc_get_settings(self, params):
        return self.service.get_settings()

    def rpc_update_settings(self, params):
        return self.service.update_settings(params.get("settings") or {})

    # -- radio, updates, packs ---------------------------------------------
    def rpc_radio_list(self, params):
        return self.service.radio_list(refresh=params.get("refresh", True))

    def rpc_check_updates(self, params):
        return self.service.check_updates(manual=bool(params.get("manual")))

    def rpc_apply_update(self, params):
        return self.service.apply_update(
            params.get("component", ""),
            url=params.get("url"),
            version=params.get("version", ""),
        )

    def rpc_offline_pack_status(self, params):
        return self.service.offline_pack_status()

    def rpc_install_offline_pack(self, params):
        return self.service.install_offline_pack(params.get("path"))

    # -- online completion (spec §11) ----------------------------------------
    def rpc_online_available(self, params):
        return {"available": self.fetcher.available()}

    def rpc_online_search(self, params):
        query = params.get("query", "")
        outcome = self.fetcher.search(query, limit=params.get("limit", 6))
        return {
            "ok": outcome.ok,
            "message": outcome.message,
            "code": getattr(outcome, "code", ""),
            "blocked": bool(getattr(outcome, "blocked", False)),
            "available": self.fetcher.available(),
            "search_url": self.fetcher.search_url(query),
            "results": [_shown(r) for r in outcome.results],
            "auto_selected": outcome.result.__dict__ if outcome.result else None,
        }

    def rpc_online_set(self, params):
        """YouTube songs for a set, in the listener's style."""
        out = self.service.online_set(params.get("event"), params.get("topic"), int(params.get("limit", 18)))
        out["results"] = [_shown(_result_from(r), in_library=r.get("in_library", False)) for r in out["results"]]
        return out

    def rpc_listen_prepare(self, params):
        """Make a YouTube song ready to play without saving it."""
        return self.service.listen_prepare(_result_from(params.get("result") or {}))

    def rpc_online_link(self, params):
        """What a pasted link is (a song, a playlist, a channel) and its songs."""
        outcome = self.fetcher.link_info(params.get("url", ""), limit=int(params.get("limit", 300)))
        have = self.service.index.video_ids()
        return {
            "ok": outcome.ok, "message": outcome.message, "code": outcome.code, "blocked": outcome.blocked,
            "kind": outcome.kind, "title": outcome.title, "artist": outcome.artist,
            "results": [_shown(r, in_library=r.id in have) for r in outcome.results],
        }

    def rpc_download_batch_async(self, params):
        """Download several songs one after another; events report each one."""
        items = [_result_from(r) for r in params.get("items") or [] if r.get("url")]
        batch_id = params.get("batch_id", "batch")

        def work():
            return dict(self.service.download_many(
                items, on_event=lambda e: self._emit("download_batch", {"batch_id": batch_id, **e})), batch_id=batch_id)

        return self._start_job("downloads", work, "download_batch_done")

    def rpc_stop_downloads(self, params):
        return self.service.stop_downloads()

    def rpc_lookup_details(self, params):
        return self.service.lookup_details(params.get("id", ""))

    def rpc_apply_details(self, params):
        return self.service.apply_details(params.get("id", ""), params.get("candidate") or {},
                                          propagate=params.get("propagate", True) is not False)

    def rpc_online_download(self, params):
        result = _result_from(params.get("result") or {})
        download_id = params.get("download_id", result.id)

        def on_progress(info: dict) -> None:
            self._emit("download_progress", {"download_id": download_id, **info})

        outcome = self.service.download_and_add(result, on_progress=on_progress)
        return {
            "ok": outcome["ok"],
            "message": outcome["message"],
            "path": outcome.get("path"),
            "track": outcome.get("track"),
            "code": outcome.get("code", ""),
            "blocked": bool(outcome.get("blocked")),
        }

    # -- loop --------------------------------------------------------------
    def serve(self, stdin=sys.stdin, stdout=sys.stdout, *, wait: bool = False) -> None:
        """Answer requests until stdin closes. ``wait`` lets pending slow
        requests finish first (tests); the app just exits."""
        self._out = stdout
        self._emit("ready", {"version": self.service.app_info()["version"]})
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = msg.get("id")
            method = msg.get("method", "")
            params = msg.get("params") or {}
            if method in _SLOW:
                self._pool.submit(self._answer, rid, method, params)
            else:
                self._answer(rid, method, params)
        self._pool.shutdown(wait=wait, cancel_futures=not wait)


def main() -> None:
    # Hebrew must survive a Windows console code page; the bridge also sets
    # PYTHONUTF8, this covers a manual run.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    # Verify HTTPS with Windows' certificate store, where a filter that
    # inspects TLS (NetFree) keeps its root certificate.
    network.use_system_trust()
    RpcServer().serve()


if __name__ == "__main__":
    main()
