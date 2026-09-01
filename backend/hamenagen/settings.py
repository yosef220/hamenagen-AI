"""User settings + application data paths (spec §16).

Settings are stored as JSON next to the app data so the whole thing stays
portable. The defaults mirror the settings screen described in the spec.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    """Where the index, models and settings live.

    Portable-first: prefer a ``data`` folder next to the app; fall back to the
    per-user app-data directory when that is not writable.
    """
    env = os.environ.get("HAMENAGEN_DATA_DIR")
    if env:
        return Path(env)
    portable = Path(__file__).resolve().parents[2] / "data"
    try:
        portable.mkdir(parents=True, exist_ok=True)
        test = portable / ".writetest"
        test.write_text("ok", encoding="utf-8")
        test.unlink()
        return portable
    except Exception:
        base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home())
        d = Path(base) / "hamenagen"
        d.mkdir(parents=True, exist_ok=True)
        return d


@dataclass
class Settings:
    # §16 — playback source: use the built-in player.
    use_builtin_player: bool = True
    # §16 — include MP4 / video files.
    include_video: bool = False
    # §16 — auto-update when online.
    auto_update: bool = True
    # Auto-play a freshly downloaded song when it finishes downloading (§11).
    autoplay_after_download: bool = True
    # Roots to scan. Empty means "scan the whole machine" (spec §9).
    scan_roots: list[str] = field(default_factory=list)
    # Enable the optional local embedding classifier layer.
    use_embeddings: bool = True
    # Which local embedding model to use (spec §8.2 layer 3, §19.3).
    # A light multilingual ONNX model run via fastembed (no PyTorch), downloaded
    # once on first run with a network, then used offline.
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # Cosine-similarity threshold above which an embedding topic is accepted.
    embedding_threshold: float = 0.5
    # Also feed song lyrics (from a sibling .lrc/.txt file) to the classifier.
    classify_by_lyrics: bool = True
    # Managed radio source (spec §13). Default: Kol Chai Music live channels.
    radio_list_url: str = "https://kcm.fm/Live/"
    # Update manifest URL (spec §14). Org-provided; empty disables update checks.
    update_manifest_url: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
            return cls(**{k: v for k, v in data.items() if k in known})
        except Exception:
            return cls()

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
