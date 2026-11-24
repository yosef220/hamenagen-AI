"""Networks that filter and inspect TLS: NetFree and the like.

A filter that inspects TLS re-signs connections with its own root
certificate, which it installs in Windows' store. :func:`use_system_trust`
makes Python verify with that store (truststore), so the update check, the
model download and song details keep working behind such a filter —
verified, never with the check turned off. The yt-dlp process does the same
on its own (see ytdlp_child).
"""

from __future__ import annotations

import sys

_trust_done = False


def use_system_trust() -> bool:
    """Verify HTTPS with the operating system's certificate store (Windows
    only; elsewhere Python already uses the system store). Safe to call more
    than once."""
    global _trust_done
    if _trust_done:
        return True
    if sys.platform != "win32":
        return False
    try:
        import truststore  # type: ignore

        truststore.inject_into_ssl()
        _trust_done = True
    except Exception:
        _trust_done = False
    return _trust_done


def get_bytes(url: str, *, timeout: float = 10.0, limit: int = 1_000_000) -> bytes | None:
    """A small file over HTTPS (verified with the system's certificates), or
    None on any failure."""
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hamenagen"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(limit + 1)
        return data if len(data) <= limit else None
    except Exception:
        return None
