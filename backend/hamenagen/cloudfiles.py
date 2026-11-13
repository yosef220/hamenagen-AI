"""Files that live only in the cloud (1.5.1).

OneDrive, Dropbox, Box, iCloud and other sync apps keep a file "online only":
it shows in the folder with its name and size, but its contents stay on the
server until something reads them. Then Windows downloads it, often with a
notification, and a cancelled download can leave the reader waiting.

The player never reads such a file by itself. The scan takes it by its file
name (no tags, no cover), and the background listening skips it. When the
listener plays it, Windows brings it down as usual, and the next scan reads
it in full. The listener can choose to read them all anyway (settings).

Windows marks these files with attributes the scan already has (``stat``
does not download anything): RECALL_ON_DATA_ACCESS (Cloud Files API:
OneDrive, Dropbox, Box…), RECALL_ON_OPEN, and OFFLINE (older providers).
"""

from __future__ import annotations

import os
import re

FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

MODES = ("skip", "read")      # skip: by name only (default); read: download and read


def attributes(st: os.stat_result | None) -> int:
    return int(getattr(st, "st_file_attributes", 0) or 0) if st is not None else 0


def is_cloud_only(st: os.stat_result | None) -> bool:
    """True when reading the file would download it first."""
    return bool(attributes(st) & CLOUD_ONLY)


def path_is_cloud_only(path) -> bool:
    try:
        return is_cloud_only(os.stat(path))
    except OSError:
        return False


_PROVIDERS = (("onedrive", "OneDrive"), ("dropbox", "Dropbox"), ("google drive", "Google Drive"),
              ("googledrive", "Google Drive"), ("icloud", "iCloud"), ("box", "Box"))


def provider(path) -> str:
    """The sync app a path most likely belongs to, for the message."""
    parts = [p.lower() for p in re.split(r"[\\/]+", str(path)) if p]
    for part in parts:
        for key, name in _PROVIDERS:
            if part == key or part.startswith(key + " ") or part.startswith(key + "-"):
                return name
    return ""
