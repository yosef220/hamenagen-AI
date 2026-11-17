"""1.6: moods that learn from the listener's marks."""

import pytest

np = pytest.importorskip("numpy")

from hamenagen import mood_learn, sound  # noqa: E402
from hamenagen.station import MOODS  # noqa: E402
from hamenagen.models import Track  # noqa: E402
from hamenagen.service import PlayerService  # noqa: E402

SIM = list(sound.SIMILARITY)


def _profile(rng, loud: list[int]):
    """A sound profile with a little of everything and a lot of ``loud``."""
    p = rng.uniform(0.0, 0.05, sound.CLASSES).astype(np.float32)
    for i in loud:
        p[SIM[i]] = rng.uniform(0.6, 0.9)
    return p


def test_marks_teach_what_a_mood_sounds_like():
    rng = np.random.default_rng(3)
    soft = [_profile(rng, [1, 2, 3]) for _ in range(5)]
    loud = [_profile(rng, [40, 41, 42]) for _ in range(5)]
    vectors = {f"s{i}": mood_learn.vector(p) for i, p in enumerate(soft)}
    vectors.update({f"l{i}": mood_learn.vector(p) for i, p in enumerate(loud)})
    marks = {"s0": 1, "s1": 1, "s2": 1, "l0": 0, "l1": 0, "l2": 0}
    model = mood_learn.fit(marks, vectors)
    assert model.learned and model.marks_yes == 3 and model.marks_no == 3
    # Songs never marked: the soft ones are pulled in, the loud ones pushed out.
    assert model.adjust(vectors["s4"]) > 0.2 > -0.2 > model.adjust(vectors["l4"])


def test_too_few_marks_teach_nothing():
    rng = np.random.default_rng(4)
    vectors = {str(i): mood_learn.vector(_profile(rng, [i])) for i in range(4)}
    model = mood_learn.fit({"0": 1, "1": 1, "2": 0}, vectors)
    assert not model.learned and model.adjust(vectors["3"]) == 0.0


def test_only_no_marks_push_out_what_sounds_like_them():
    rng = np.random.default_rng(5)
    drums = [_profile(rng, [60, 61]) for _ in range(4)]
    others = [_profile(rng, [5 + 7 * k, 6 + 7 * k]) for k in range(6)]   # the rest of the library
    vectors = {str(i): mood_learn.vector(p) for i, p in enumerate(drums)}
    vectors.update({f"o{k}": mood_learn.vector(p) for k, p in enumerate(others)})
    model = mood_learn.fit({"0": 0, "1": 0, "2": 0}, vectors)
    assert model.adjust(vectors["3"]) < -0.3
    assert all(model.adjust(vectors[f"o{k}"]) == 0.0 for k in range(6))


def test_a_marked_song_is_always_in_and_never_out(tmp_path):
    service = PlayerService(data_dir=tmp_path / "data")
    try:
        for i in range(8):
            service.index.upsert(Track(id=str(i), path=f"/m/{i}.mp3", title=f"שיר {i}", duration=200))
            service.index.save_analysis(str(i), {"energy": 0.2 + 0.05 * i, "tempo": 90.0})
        mood = next(m for m in MOODS if m.key == "calm")
        assert service.set_mood_mark("7", "calm", True)["yes"] == 1     # the loudest, marked calm
        r = service.set_mood_mark("0", "calm", False)                    # the softest, marked not
        assert (r["no"], r["min"]) == (1, 3)
        ids = [t.id for t in service._mood_tracks(mood, 10)]
        assert ids[0] == "7" and "0" not in ids
        assert service._tracks_payload([service.index.get("7")])[0]["moods"] == {"calm": 1}
        assert service.set_mood_mark("7", "calm", None)["yes"] == 0
        assert not service.set_mood_mark("7", "no-such-mood", True)["ok"]
    finally:
        service.close()
