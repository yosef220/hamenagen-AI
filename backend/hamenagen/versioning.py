"""Tiny semantic-version helpers shared by the updater and the offline pack."""

from __future__ import annotations

import re

_NUM_RE = re.compile(r"\d+")


def version_tuple(v: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple of ints.

    Non-numeric segments are reduced to their leading digits (0 if none), so
    "1.5.17", "2024.1.0" and "v0.1" all parse sensibly.
    """
    if not v:
        return (0,)
    parts = []
    for seg in str(v).strip().lstrip("vV").split("."):
        m = _NUM_RE.match(seg)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts) or (0,)


def compare(a: str, b: str) -> int:
    """Return -1 if a<b, 0 if equal, 1 if a>b (numeric, length-normalised)."""
    ta, tb = version_tuple(a), version_tuple(b)
    n = max(len(ta), len(tb))
    ta += (0,) * (n - len(ta))
    tb += (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


def is_newer(candidate: str, current: str) -> bool:
    """True if ``candidate`` is a strictly newer version than ``current``."""
    return compare(candidate, current) > 0
