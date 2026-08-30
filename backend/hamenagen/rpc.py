"""Line-delimited JSON-RPC bridge over stdio (Electron ↔ Python).

The Electron main process spawns ``python -m hamenagen.rpc`` and exchanges
newline-delimited JSON messages with it:

    request : {"id": 1, "method": "handle_request", "params": {"text": "..."}}
    response: {"id": 1, "ok": true, "result": {...}}
    error   : {"id": 1, "ok": false, "error": "..."}

Keeping the transport this simple (no HTTP server, no ports) keeps the app
portable and avoids opening any network socket on the user's machine.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from .fetcher import SearchResult
from .service import PlayerService


class RpcServer:
    def __init__(self) -> None:
        self.service = PlayerService()
        self.fetcher = self.service.fetcher
        self._out = sys.stdout  # set for real in serve(); used by progress hook

    def _emit(self, event: str, payload: dict) -> None:
        """Push an out-of-band notification (no id) to the client, e.g. progress."""
        self._out.write(json.dumps({"event": event, **payload}, ensure_ascii=False) + "\n")
        self._out.flush()

    # Each handler takes a params dict and returns a JSON-serialisable value.
    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handler = getattr(self, f"rpc_{method}", None)
        if handler is None:
            raise ValueError(f"unknown method: {method}")
        return handler(params)

    # -- methods -----------------------------------------------------------
    def rpc_ping(self, params):
        return {"pong": True}

    def rpc_handle_request(self, params):
        return self.service.handle_request(params.get("text", ""))

    def rpc_rescan(self, params):
        return self.service.rescan(params.get("roots"))

    def rpc_opening_suggestion(self, params):
        return self.service.opening_suggestion()

    def rpc_get_settings(self, params):
        from dataclasses import asdict

        return asdict(self.service.settings)

    def rpc_update_settings(self, params):
        s = self.service.settings
        for key, value in (params.get("settings") or {}).items():
            if hasattr(s, key):
                setattr(s, key, value)
        s.save(self.service.data_dir / "settings.json")
        from dataclasses import asdict

        return asdict(s)

    def rpc_online_search(self, params):
        query = params.get("query", "")
        outcome = self.fetcher.search(query, limit=params.get("limit", 5))
        return {
            "ok": outcome.ok,
            "message": outcome.message,
            "available": self.fetcher.available(),
            "search_url": self.fetcher.search_url(query),
            "results": [r.__dict__ for r in outcome.results],
            "auto_selected": outcome.result.__dict__ if outcome.result else None,
        }

    def rpc_online_download(self, params):
        r = params.get("result") or {}
        result = SearchResult(
            source=r.get("source", "youtube"),
            id=r.get("id", ""),
            title=r.get("title", ""),
            url=r.get("url", ""),
            uploader=r.get("uploader", ""),
            duration=r.get("duration"),
            upload_date=r.get("upload_date"),
        )
        download_id = params.get("download_id", result.id)

        def on_progress(info: dict) -> None:
            self._emit("download_progress", {"download_id": download_id, **info})

        outcome = self.service.download_and_add(result, on_progress=on_progress)
        return {
            "ok": outcome["ok"],
            "message": outcome["message"],
            "path": outcome.get("path"),
            "track": outcome.get("track"),
        }

    # -- loop --------------------------------------------------------------
    def serve(self, stdin=sys.stdin, stdout=sys.stdout) -> None:
        self._out = stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = msg.get("id")
            try:
                result = self._dispatch(msg.get("method", ""), msg.get("params") or {})
                out = {"id": rid, "ok": True, "result": result}
            except Exception as exc:  # noqa: BLE001 - report all errors to caller
                out = {
                    "id": rid,
                    "ok": False,
                    "error": str(exc),
                    "trace": traceback.format_exc(),
                }
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> None:
    RpcServer().serve()


if __name__ == "__main__":
    main()
