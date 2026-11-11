"""Tests for the embedding classifier layer (spec §8.2 layer 3).

The real model is not downloaded in tests. We check that:
1. the real backend degrades gracefully when the model is not available;
2. the typical-phrase logic (closest phrase, threshold, margin) picks the
   right topic, using a stand-in for the neural encoder;
3. the hybrid classifier falls through to an embedding backend only when
   the curated layers do not match.
"""

import pytest

np = pytest.importorskip("numpy")

from hamenagen.classifier import MODELS, Classification, EmbeddingBackend, HybridClassifier


def test_real_backend_status_without_model(tmp_path):
    backend = EmbeddingBackend("no/such-model-xyz", cache_dir=str(tmp_path))
    st = backend.status()
    assert st["available"] is False
    assert st["model"] == "no/such-model-xyz"
    # classify() must never raise, just return None when unavailable.
    assert backend.classify("שיר כלשהו") is None


def test_default_model_without_files_and_no_download(tmp_path):
    backend = EmbeddingBackend(cache_dir=str(tmp_path), allow_download=False)
    assert backend.load() is False
    assert "not installed" in (backend.load_error or "")
    assert backend.status()["cached"] is False


def test_default_model_is_pinned():
    spec = MODELS["intfloat/multilingual-e5-small"]
    assert len(spec["revision"]) == 40
    assert spec["prefix"] == "query: "


class StubBackend(EmbeddingBackend):
    """The real phrase-matching logic over a fake three-word "encoder"."""

    WORDS = ["נר", "סוכה", "חתן"]

    def __init__(self):
        super().__init__(threshold=0.8)
        self.margin = 0.05

    def load(self):
        self._np = np
        self._session = object()
        self.available = True
        self._topics = ["חנוכה", "סוכות", "חתונה"]
        phrases = ["נר", "סוכה", "חתן"]
        self._phrase_topic = [0, 1, 2]
        self._matrix = self._embed(phrases)
        return True

    def _embed(self, texts):
        out = []
        for t in texts:
            v = np.array([t.count(w) for w in self.WORDS], dtype=np.float32) + 0.01
            out.append(v / np.linalg.norm(v))
        return np.array(out)


def test_closest_phrase_with_threshold_and_margin():
    b = StubBackend()
    b.load()
    assert b.classify("נר ועוד נר").topic == "חנוכה"
    # Two topics equally close: not clearly ahead, so no answer.
    assert b.classify("נר וסוכה") is None
    # Nothing close enough.
    assert b.classify("שיר על הים") is None
    scores = b.topic_scores("חתן")
    assert max(scores, key=scores.get) == "חתונה"


class FakeBackend:
    """Stand-in embedding backend: keys on a phrase that is NOT in the curated
    lexicon, so it only fires via the embedding fall-through (layer 4)."""

    def __init__(self):
        self.available = True

    def classify(self, text, *, threshold=None):
        if "מחילה" in text:  # not a curated keyword
            return Classification("אלול", "embedding", 0.91)
        return None


def test_hybrid_falls_through_to_embeddings():
    clf = HybridClassifier(embedding_backend=FakeBackend())
    # No curated keyword/title hit, but the embedding backend catches it.
    c = clf.classify(title="שיר ללא מילת מפתח", lyrics="קולות של רחמים ומחילה")
    assert c.topic == "אלול"
    assert c.source == "embedding"


def test_embeddings_skipped_when_disabled():
    clf = HybridClassifier(embedding_backend=FakeBackend())
    c = clf.classify(title="שיר ללא מילת מפתח", lyrics="רחמים ומחילה", use_embeddings=False)
    assert c.topic is None
    assert c.source == "none"
