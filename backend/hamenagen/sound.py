"""What a song sounds like, from what the background listening already hears.

The vocal detector (vocal.py) runs the CED audio tagger on three windows of
every song; it answers with 527 AudioSet probabilities per window. Here those
answers are kept as a *sound profile* and read for three more things:

* **speech or music** — recordings of a talk or a shiur (and spoken stories)
  are kept out of mixes, sets and the radio. Measured on real recordings: in
  songs "Speech" stays at or below 0.03 and "Music" at 0.49–0.82; in spoken
  recordings "Speech" is 0.78–0.82 with no music; a talk over music at
  −12 dB still reads 0.63 against 0.58; a song that opens with a few spoken
  words stays a song (the middle of three windows decides).
* **how alike two songs sound** — the cosine of their profiles over the
  musical classes (singing, instruments, genres, moods), for "songs like this
  one" and the radio.
* **leading and trailing silence** — read from the first and last seconds of
  the file, so the player can skip them and move on when the music ends.

The genre and mood classes (electronic, Middle Eastern, children's music…)
were not measured on this community's music, so they only rank and compare
songs; they are never shown to the listener as a label.
"""

from __future__ import annotations

import math
import re

PROFILE_VERSION = 1
CLASSES = 527

# AudioSet indices (class_labels_indices.csv).
SPEECH = (0, 1, 2, 3, 4, 5)      # Speech, male/female/child speech, conversation, narration
MUSIC = 137
# What two songs are compared on: singing (27–37) and everything musical
# from "Music" to the moods (137–282); not noises, rooms or speech.
SIMILARITY = tuple(range(27, 38)) + tuple(range(137, 283))

# Soft style scores (ranking only; see the module note).
FACETS: dict[str, tuple[int, ...]] = {
    "electronic": (239, 240, 241, 242, 243, 244, 245, 247, 158),
    "middle_eastern": (234,),
    "children": (252, 34),
    "choir": (28,),
    "orchestral": (184, 190, 237),
    "rock": (219, 220, 221, 224, 141),
    "acoustic": (143, 153, 191, 193, 196, 198, 199),
    "dance": (274, 236),
    "wedding": (275,),
    "happy": (276,),
    "sad": (278,),
    "tender": (279, 271),
    "exciting": (280,),
}

SPEECH_MIN = 0.5
# Words that mark a spoken recording whatever the audio says.
SPEECH_WORDS = ("שיעור", "הרצאה", "דרשה", "דברי תורה", "מפי הרב", "הספד", "דברי פתיחה", "דברי הסבר",
                "שיחת התעוררות")
_WORD_RE = re.compile("|".join(re.escape(w) for w in SPEECH_WORDS))

# Silence at the edges: a 50 ms frame quieter than this is silence.
SILENCE_DB = -45.0
EDGE_SECONDS = 20.0
LEAD_MIN, TAIL_MIN = 0.6, 1.5          # shorter gaps are part of the song
LEAD_KEEP, TAIL_KEEP = 0.15, 0.3        # start a moment before the sound; end a moment after it


# ------------------------------------------------------------------ profiles
def summarize(window_probs) -> dict:
    """What to keep from the per-window probabilities (rows × 527)."""
    import numpy as np

    p = np.asarray(window_probs, dtype=np.float32)
    if p.ndim != 2 or p.shape[0] == 0 or p.shape[1] != CLASSES:
        return {}
    speech = p[:, SPEECH].max(axis=1)
    return {
        "profile": pack(p.mean(axis=0)),
        "speech": round(float(np.median(speech)), 4),
        "music": round(float(np.median(p[:, MUSIC])), 4),
        "profile_v": PROFILE_VERSION,
    }


def pack(vector) -> bytes:
    import numpy as np

    return np.asarray(vector, dtype=np.float16).tobytes()


def unpack(blob):
    """The profile as numpy float32 (None when missing or malformed)."""
    if not blob or len(blob) != 2 * CLASSES:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    v = np.frombuffer(blob, dtype=np.float16)
    return v.astype(np.float32) if v.size == CLASSES else None


def similarity(a, b) -> float:
    """How alike two profiles sound, 0–1 (cosine over the musical classes;
    square roots, so a few loud classes do not drown the rest)."""
    if a is None or b is None:
        return 0.0
    import numpy as np

    x = np.sqrt(np.clip(a[list(SIMILARITY)], 0, 1))
    y = np.sqrt(np.clip(b[list(SIMILARITY)], 0, 1))
    den = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float(x @ y) / den if den else 0.0


def facets(profile) -> dict[str, float]:
    if profile is None:
        return {}
    return {name: float(max(profile[i] for i in idx)) for name, idx in FACETS.items()}


# ------------------------------------------------------------------ speech
def speech_by_words(text: str) -> bool:
    return bool(text and _WORD_RE.search(text))


def is_speech(analysis: dict | None, text: str = "", override: dict | None = None) -> bool:
    """A spoken recording (a talk, a shiur, a story) rather than a song.

    The listener's choice wins; then the words in the name; then the audio:
    speech at least ``SPEECH_MIN`` in the middle window and no weaker than
    the music."""
    if override and override.get("speech") is not None:
        return bool(override["speech"])
    if speech_by_words(text):
        return True
    a = analysis or {}
    speech, music = a.get("speech"), a.get("music")
    if speech is None:
        return False
    return speech >= SPEECH_MIN and speech >= (music or 0.0)


# ------------------------------------------------------------------ silence
def _frame_db(np, x, sr: int):
    hop = max(1, int(0.05 * sr))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0), hop
    frames = x[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-9)), hop


def silence_edges(path, sf, np) -> dict | None:
    """Seconds of silence at the start and the end of a file (0 when there
    is none worth skipping). ``None`` when the file cannot be read."""
    try:
        with sf.SoundFile(str(path)) as f:
            sr, frames = f.samplerate, f.frames
            if sr <= 0 or frames <= 0:
                return None
            span = min(frames, int(EDGE_SECONDS * sr))
            head = f.read(span, dtype="float32", always_2d=True).mean(axis=1)
            f.seek(max(0, frames - span))
            tail = f.read(span, dtype="float32", always_2d=True).mean(axis=1)
    except Exception:  # noqa: BLE001 - a file it cannot read keeps its edges
        return None
    duration = frames / sr
    out = {"lead": 0.0, "tail": 0.0}
    db, hop = _frame_db(np, head, sr)
    loud = np.nonzero(db > SILENCE_DB)[0]
    if len(loud):
        lead = loud[0] * hop / sr - LEAD_KEEP
        if lead >= LEAD_MIN:
            out["lead"] = round(lead, 2)
    db, hop = _frame_db(np, tail, sr)
    loud = np.nonzero(db > SILENCE_DB)[0]
    if len(loud):
        end_in_tail = (loud[-1] + 1) * hop / sr
        trailing = len(tail) / sr - end_in_tail - TAIL_KEEP
        if trailing >= TAIL_MIN:
            out["tail"] = round(trailing, 2)
    # Never skip so much that little of a short song is left.
    if out["lead"] + out["tail"] > 0.5 * duration:
        return {"lead": 0.0, "tail": 0.0}
    return out


# ------------------------------------------------------------------ loudness
TARGET_DB = -14.0          # RMS of the 16 kHz windows (rhythm.py "loudness")
MAX_CUT_DB = 12.0


def gain_db(loudness: float | None) -> float:
    """How much quieter to play a song so loud songs match the rest (0 or
    negative: the player only turns down, so it never distorts)."""
    if loudness is None or not math.isfinite(loudness):
        return 0.0
    return round(-min(MAX_CUT_DB, max(0.0, loudness - TARGET_DB)), 1)
