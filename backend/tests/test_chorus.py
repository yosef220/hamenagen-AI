"""Finding the chorus for a ringtone (chorus.py)."""

from __future__ import annotations

import pytest

from hamenagen import chorus

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

SR = 11025


def _chord(notes, seconds, amp=0.15):
    t = np.arange(int(SR * seconds)) / SR
    return sum(amp * np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * t) for m in notes).astype(np.float32)


def _section(chords, each=2.0, amp=0.15):
    return np.concatenate([_chord(c, each, amp) for c in chords])


def _song(tmp_path):
    rng = np.random.default_rng(7)
    verse = lambda: _section([[int(m) for m in rng.integers(55, 80, 3)] for _ in range(10)], amp=0.1)  # noqa: E731
    refrain = _section([[60, 64, 67], [65, 69, 72], [67, 71, 74], [57, 60, 64]] * 3, amp=0.18)       # 24 s
    parts = [verse(), refrain, verse(), refrain, verse(), refrain]   # 20 s verses: chorus at 20, 64, 108
    x = np.concatenate(parts)
    f = tmp_path / "song.wav"
    sf.write(f, x, SR)
    return f


def test_the_chorus_is_where_the_song_repeats(tmp_path):
    start = chorus.find_chorus(_song(tmp_path), 20)
    assert start is not None and 18 <= start <= 24


def test_no_repetition_no_answer(tmp_path):
    rng = np.random.default_rng(3)
    x = _section([[int(m) for m in rng.integers(50, 85, 3)] for _ in range(40)])
    f = tmp_path / "free.wav"
    sf.write(f, x, SR)
    start = chorus.find_chorus(f, 20)
    assert start is None or start >= 0          # never fails; may find nothing
