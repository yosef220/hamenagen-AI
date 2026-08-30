"""Tests for the embedding classifier layer (spec §8.2 layer 3).

We do not download the real model in CI. Instead we verify:
1. the real backend degrades gracefully when the package/model is absent;
2. the hybrid classifier correctly falls through to an *injected* embedding
   backend when the curated layers do not match, and honours its result.
"""

from hamenagen.classifier import Classification, EmbeddingBackend, HybridClassifier


def test_real_backend_status_without_model():
    backend = EmbeddingBackend("no/such-model-xyz")
    st = backend.status()
    assert st["available"] is False
    assert st["model"] == "no/such-model-xyz"
    # classify() must never raise, just return None when unavailable.
    assert backend.classify("שיר כלשהו") is None


class FakeBackend:
    """Stand-in embedding backend: keys on a phrase that is NOT in the curated
    lexicon, so it only fires via the embedding fall-through (layer 4)."""

    def __init__(self):
        self.available = True

    def classify(self, text, *, threshold=None):
        if "נוראים" in text:  # not a curated keyword
            return Classification("אלול", "embedding", 0.71)
        return None


def test_hybrid_falls_through_to_embeddings():
    clf = HybridClassifier(embedding_backend=FakeBackend())
    # No curated keyword/title hit, but the embedding backend catches it.
    c = clf.classify(title="שיר ללא מילת מפתח", lyrics="ימים נוראים מתקרבים")
    assert c.topic == "אלול"
    assert c.source == "embedding"


def test_embeddings_skipped_when_disabled():
    clf = HybridClassifier(embedding_backend=FakeBackend())
    c = clf.classify(title="שיר ללא מילת מפתח", lyrics="ימים נוראים", use_embeddings=False)
    assert c.topic is None
    assert c.source == "none"
