"""The yt-dlp process the app starts (see ytdlp_runner).

Runs yt-dlp with the newer copy from the data folder when there is one, and
with the operating system's certificate store (truststore), so a network
that inspects TLS with a certificate Windows trusts (NetFree) still works.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    engine = os.environ.get("HAMENAGEN_ENGINE_DIR") or ""
    if engine and os.path.isfile(os.path.join(engine, "yt_dlp", "__init__.py")):
        sys.path.insert(0, engine)
    try:
        import truststore  # type: ignore

        truststore.inject_into_ssl()
    except Exception:
        pass
    import yt_dlp  # type: ignore

    try:
        return yt_dlp.main(sys.argv[1:]) or 0
    except SystemExit as exc:  # yt-dlp ends with sys.exit
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)


if __name__ == "__main__":
    sys.exit(main())
