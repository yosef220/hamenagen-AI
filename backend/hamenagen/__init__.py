"""hamenagen — נגן מוזיקה קהילתי חכם (Smart Community Music Player) core.

This package contains the offline-first "smart" core of the player:
library scanning, a local metadata index, Hebrew natural-language intent
parsing, fuzzy song matching, topical classification and a Hebrew-calendar
based suggestion engine.

The core is intentionally free of any GUI dependency so it can be driven
either by the Electron front-end (via :mod:`hamenagen.rpc`) or from the
command line (via :mod:`hamenagen.cli`), and unit-tested on its own.
"""

__version__ = "0.1.0"
