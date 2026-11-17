"""1.6: the key of a song, from the same windows as its tempo, and keys that
sit well together in a set."""

import pytest

np = pytest.importorskip("numpy")

from hamenagen import sets as sets_mod  # noqa: E402
from hamenagen.rhythm import analyze_windows, camelot, key_distance, key_name  # noqa: E402

SR = 16000
I, IV, V = [0, 4, 7], [5, 9, 12], [7, 11, 14]
i, iv = [0, 3, 7], [5, 8, 12]


def _progression(chords, base):
    def chord(notes, secs=1.25):
        t = np.arange(int(SR * secs)) / SR
        return sum(np.sin(2 * np.pi * 440 * 2 ** ((base + n - 69) / 12) * t) * 0.2 for n in notes)
    x = np.concatenate([chord(c) for c in chords]).astype(np.float32)
    return [x, x, x]


@pytest.mark.parametrize("chords,base,expected", [
    ([I, IV, V, I] * 2, 60, "דו מז׳ור"),
    ([I, IV, V, I] * 2, 55, "סול מז׳ור"),
    ([i, iv, V, i] * 2, 57, "לה מינור"),
    ([i, iv, V, i] * 2, 52, "מי מינור"),
])
def test_the_key_of_a_progression(chords, base, expected):
    r = analyze_windows(_progression(chords, base))
    assert key_name(r["musical_key"]) == expected and r["key_conf"] > 0.1


def test_noise_has_no_key():
    rng = np.random.default_rng(1)
    x = (rng.standard_normal(SR * 10) * 0.2).astype(np.float32)
    assert analyze_windows([x, x, x])["musical_key"] == -1
    assert key_name(-1) == "" and key_name(None) == ""


def test_keys_that_sit_together():
    c, g, am, fsharp = 0, 7, 12 + 9, 6
    assert camelot(c)[0] == camelot(am)[0]               # relative major and minor
    assert key_distance(c, c) == 0
    assert key_distance(c, g) == 1 and key_distance(c, am) == 1
    assert key_distance(c, fsharp) == 6
    assert key_distance(c, -1) == 1.5 and key_distance(None, c) == 1.5


def test_a_set_prefers_a_neighbouring_key():
    first = sets_mod.SetSong("a", 120, 0.2, key=0)
    near = sets_mod.SetSong("near", 120, 0.6, key=7)      # G after C
    far = sets_mod.SetSong("far", 120, 0.6, key=6)        # F# after C
    order = sets_mod.arrange([first, far, near, sets_mod.SetSong("z", 120, 0.9, key=7)], seed=1)
    assert [s.track for s in order][:2] == ["a", "near"]
