"""Moods that learn from the listener's own marks (1.6).

"משהו רגוע", "שירים מרגשים", "שירים לילדים" are ranked by how a song sounds
(station.score_for_mood). The listener can mark a song "fits" or "does not
fit" a mood, from the song's menu. A marked song is always in (or always out
of) that mood, and the marks teach the player what the mood sounds like to
this listener:

* from MIN_MARKS "no" marks, songs that sound like them (the sound profile,
  sound.py) are pushed out of the mood;
* from MIN_MARKS "yes" marks, songs that sound like them are pulled in;
* with both, a small logistic model on the profile learns the line between
  them, and is used only when it separates the marks it learned from better
  than the plain likeness to each side does (checked by leaving each mark out
  in turn).

Pure numpy; nothing leaves the computer.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import sound

MIN_MARKS = 3
# How alike (cosine, once the library's average sound is taken off) a song
# must be to the marked ones before the marks move it.
LIKE = 0.3
# The vectors are unit length over ~150 classes (each part small): scaled up
# for the logistic model, so that it learns in a few hundred steps.
_SCALE = 10.0


def vector(profile):
    """The part of a song's sound profile moods are learned on: the musical
    classes, square roots (as sound.similarity), unit length."""
    if profile is None:
        return None
    import numpy as np

    x = np.sqrt(np.clip(profile[list(sound.SIMILARITY)], 0, 1)).astype(np.float64)
    n = float(np.linalg.norm(x))
    return x / n if n else None


def _centroid(np, vecs):
    if not vecs:
        return None
    c = np.mean(vecs, axis=0)
    n = float(np.linalg.norm(c))
    return c / n if n else None


def _logistic(np, X, y, l2: float = 1.0, steps: int = 400, lr: float = 0.5):
    """Weights (with the bias last) of an L2-regularised logistic model."""
    Xb = np.hstack([X, np.ones((len(X), 1))])
    w = np.zeros(Xb.shape[1])
    pos = max(1, int(y.sum()))
    neg = max(1, len(y) - pos)
    weight = np.where(y > 0, len(y) / (2 * pos), len(y) / (2 * neg))   # both sides count the same
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(Xb @ w)))
        grad = Xb.T @ ((p - y) * weight) / len(y) + l2 * np.r_[w[:-1], 0] / len(y)
        w -= lr * grad
    return w


@dataclass
class MoodModel:
    center: object = None       # the library's average sound, taken off every song
    yes: object = None          # centroid of the songs marked "fits"
    no: object = None           # centroid of the songs marked "does not fit"
    weights: object = None      # logistic weights, when they proved better
    marks_yes: int = 0
    marks_no: int = 0

    @property
    def learned(self) -> bool:
        return self.yes is not None or self.no is not None

    def adjust(self, vec) -> float:
        """How much the marks move a song toward the mood (+) or away (−),
        about −1…1."""
        if vec is None or not self.learned:
            return 0.0
        import numpy as np

        vec = _centered(np, vec, self.center)
        if vec is None:
            return 0.0
        if self.weights is not None:
            z = float(_SCALE * vec @ self.weights[:-1]) + float(self.weights[-1])
            p = 1 / (1 + np.exp(-max(-30.0, min(30.0, z))))
            return 2.0 * (p - 0.5)
        out = 0.0
        if self.yes is not None:
            out += max(0.0, float(vec @ self.yes) - LIKE) * 2.0
        if self.no is not None:
            out -= max(0.0, float(vec @ self.no) - LIKE) * 2.0
        return max(-1.0, min(1.0, out))


def _centered(np, vec, center):
    """A song's sound less what every song has, unit length: what sets it apart."""
    x = vec - center if center is not None else vec
    n = float(np.linalg.norm(x))
    return x / n if n > 1e-9 else None


def fit(marks: dict[str, int], vectors: dict[str, object]) -> MoodModel:
    """A mood's model from the listener's marks ({song id: 1 fits, 0 not}).
    ``vectors``: every song's vector (the library), marked or not."""
    import numpy as np

    known = [v for v in vectors.values() if v is not None]
    center = np.mean(known, axis=0) if len(known) >= 2 else None

    def side(value):
        out = []
        for i, v in marks.items():
            if v == value and vectors.get(i) is not None:
                c = _centered(np, vectors[i], center)
                if c is not None:
                    out.append(c)
        return out

    yes, no = side(1), side(0)
    model = MoodModel(center=center, marks_yes=len(yes), marks_no=len(no))
    if len(yes) >= MIN_MARKS:
        model.yes = _centroid(np, yes)
    if len(no) >= MIN_MARKS:
        model.no = _centroid(np, no)
    if len(yes) >= MIN_MARKS and len(no) >= MIN_MARKS:
        X = np.array(yes + no) * _SCALE
        y = np.array([1.0] * len(yes) + [0.0] * len(no))
        # Leave one out: is the logistic line better than plain likeness?
        right_lr = right_near = 0
        for k in range(len(X)):
            keep = np.arange(len(X)) != k
            w = _logistic(np, X[keep], y[keep])
            right_lr += int((float(X[k] @ w[:-1] + w[-1]) > 0) == bool(y[k]))
            cy = _centroid(np, list(X[keep][y[keep] > 0]))
            cn = _centroid(np, list(X[keep][y[keep] == 0]))
            right_near += int((float(X[k] @ cy) > float(X[k] @ cn)) == bool(y[k]))
        if right_lr > right_near:
            model.weights = _logistic(np, X, y)
    return model
