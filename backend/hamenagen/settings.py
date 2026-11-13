"""User settings + application data paths (spec §16).

Settings are stored as JSON in the data folder so the whole thing stays
portable. The defaults mirror the settings screen described in the spec.

Where things live is decided by the Electron shell, which knows the edition
and passes it in the environment:

* ``HAMENAGEN_DATA_DIR``   — library, settings, favorites, downloaded model
* ``HAMENAGEN_MODELS_DIR`` — a model bundled inside the app (offline edition)
* ``HAMENAGEN_MUSIC_DIR``  — the user's Music folder (downloads go under it)
* ``HAMENAGEN_EDITION``    — "portable" | "offline" | "setup" | "dev"

Run on its own (CLI, tests) the core falls back to sensible defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_UPDATE_MANIFEST = "https://github.com/yosef220/hamenagen-AI/releases/latest/download/update.json"
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
# Models of earlier versions; settings that still name one move to the default.
_RETIRED_MODELS = {"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"}

THEMES = ("system", "light", "dark")
TEXT_SIZES = ("normal", "large", "xlarge")


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".writetest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def default_data_dir() -> Path:
    """Where the index, models and settings live.

    Portable-first: prefer a ``data`` folder next to the app; fall back to the
    per-user app-data directory when that is not writable.
    """
    env = os.environ.get("HAMENAGEN_DATA_DIR")
    if env:
        return Path(env)
    portable = Path(__file__).resolve().parents[2] / "data"
    if _writable(portable):
        return portable
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home())
    d = Path(base) / "Hamenagen"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_models_dir() -> Path | None:
    """A model shipped inside the app (the offline edition), if any."""
    env = os.environ.get("HAMENAGEN_MODELS_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return None


def bundled_audio_models_dir() -> Path | None:
    """The vocal-detection model shipped inside the app (every edition)."""
    env = os.environ.get("HAMENAGEN_AUDIO_MODELS_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return None


def bundled_voice_models_dir() -> Path | None:
    """The speech model shipped inside the app (the offline editions): its
    own part, so the smart update never sends the classification model
    again when only one of them changes."""
    env = os.environ.get("HAMENAGEN_VOICE_MODELS_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return None


def bundled_ffmpeg_dir() -> Path | None:
    """ffmpeg shipped inside the app, for MP3 downloads with covers."""
    env = os.environ.get("HAMENAGEN_FFMPEG_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return None


def default_downloads_dir() -> Path:
    music = os.environ.get("HAMENAGEN_MUSIC_DIR")
    base = Path(music) if music else Path.home() / "Music"
    return base / "Hamenagen"


def edition() -> str:
    return os.environ.get("HAMENAGEN_EDITION", "dev")


def _clamp(value, low: int, high: int) -> int:
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return low


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
    # Folders to scan. Empty means "the whole computer" (spec §9).
    scan_roots: list[str] = field(default_factory=list)
    # Where songs downloaded from the network are saved. Empty = Music\Hamenagen.
    downloads_dir: str = ""
    # Enable the optional local embedding classifier layer.
    use_embeddings: bool = True
    # Which local embedding model to use (spec §8.2 layer 3, §19.3).
    # A small multilingual ONNX model run with ONNX Runtime (no PyTorch), shipped
    # in the offline edition or downloaded once on first run, then offline.
    embedding_model: str = DEFAULT_MODEL
    # Similarity to a topic's closest typical phrase needed to accept it
    # (calibrated for the default model; see backend/scripts/benchmark_models.py).
    embedding_threshold: float = 0.91
    # Also feed song lyrics (from a sibling .lrc/.txt file) to the classifier.
    classify_by_lyrics: bool = True
    # Suggest a cappella music in the Omer count and the Three Weeks.
    vocal_suggestions: bool = True
    # Listen to three short windows of every song and recognise singing with
    # no instruments (vocal.py). Runs in the background, offline.
    vocal_detection: bool = True
    # Count songs the detector found as "ווקאלי" right away. Off: they wait in
    # a list for the listener to confirm, and only confirmed songs are
    # suggested in the Omer count and the Three Weeks.
    vocal_auto_include: bool = False
    # Hear each song's tempo and energy (rhythm.py), for the "סט לשמחה".
    rhythm_analysis: bool = True
    # A soft transition between songs: seconds of crossfade (0 = none).
    crossfade_seconds: int = 0
    # Appearance: "system" | "light" | "dark", and the text size.
    theme: str = "system"
    text_size: str = "normal"
    # Managed radio source (spec §13). Default: Kol Chai Music live channels.
    radio_list_url: str = "https://kcm.fm/Live/"
    # Update manifest URL (spec §14): the update.json of the latest release.
    update_manifest_url: str = DEFAULT_UPDATE_MANIFEST
    # Show each song once when it is in several folders or formats.
    hide_duplicates: bool = True
    # Shabbat and festival mode: the music fades out and stops before candle
    # lighting, and "שבת שלום" stays on screen until Shabbat ends (zmanim.py).
    shabbat_mode: bool = True
    shabbat_city: str = "ירושלים"
    # Candle lighting, minutes before sunset; 0 = the city's custom.
    candle_minutes: int = 0
    # Stop the music this many minutes before candle lighting.
    shabbat_stop_before: int = 10
    # The end of Shabbat: "tzeit" (nightfall, 8.5°) or "rt" (Rabbeinu Tam).
    havdalah: str = "tzeit"
    # 1.4: play loud songs a little quieter, so all songs sound about as loud.
    normalize_volume: bool = True
    # 1.4: skip silence at the start and the end of a song.
    skip_silence: bool = True
    # 1.4: folders whose songs never play in mixes, sets or the radio (they
    # still play when chosen, and are found in searches).
    isolated_folders: list = field(default_factory=list)
    # 1.5: stations the listener added by address ([{title, url}], https only:
    # the window plays secure addresses only).
    custom_stations: list = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
            s = cls(**{k: v for k, v in data.items() if k in known})
        except Exception:
            return cls()
        # 0.1 shipped an empty manifest URL; point old settings at releases.
        if not s.update_manifest_url:
            s.update_manifest_url = DEFAULT_UPDATE_MANIFEST
        # 0.1 used another model with another scale of similarity.
        if s.embedding_model in _RETIRED_MODELS:
            s.embedding_model = DEFAULT_MODEL
            s.embedding_threshold = 0.91
        return s.sanitized()

    def sanitized(self) -> "Settings":
        if self.theme not in THEMES:
            self.theme = "system"
        if self.text_size not in TEXT_SIZES:
            self.text_size = "normal"
        self.scan_roots = [str(r) for r in (self.scan_roots or []) if str(r).strip()]
        self.isolated_folders = [str(r) for r in (self.isolated_folders or []) if str(r).strip()]
        stations = []
        for s in self.custom_stations or []:
            if isinstance(s, dict):
                title, url = str(s.get("title") or "").strip()[:80], str(s.get("url") or "").strip()
                if url.lower().startswith("https://") and len(url) < 1000:
                    stations.append({"title": title or url.split("/")[2], "url": url})
        self.custom_stations = stations[:50]
        from .zmanim import CITIES, DEFAULT_CITY, HAVDALAH_CHOICES
        if self.shabbat_city not in CITIES:
            self.shabbat_city = DEFAULT_CITY
        self.candle_minutes = _clamp(self.candle_minutes, 0, 90)
        self.shabbat_stop_before = _clamp(self.shabbat_stop_before, 0, 120)
        self.crossfade_seconds = _clamp(self.crossfade_seconds, 0, 12)
        if self.havdalah not in HAVDALAH_CHOICES:
            self.havdalah = "tzeit"
        return self

    def update(self, values: dict) -> list[str]:
        """Apply the known keys of ``values``; returns the keys that changed."""
        changed = []
        for key, value in (values or {}).items():
            if key in self.__dataclass_fields__ and getattr(self, key) != value:  # type: ignore[attr-defined]
                setattr(self, key, value)
                changed.append(key)
        self.sanitized()
        return changed

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
