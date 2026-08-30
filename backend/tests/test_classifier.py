from hamenagen.classifier import HybridClassifier


def test_title_override_without_keyword():
    # The spec's flagship example: "מנוחה ושמחה" -> שבת even without "שבת".
    c = HybridClassifier().classify(title="מנוחה ושמחה", artist="מקהלה")
    assert c.topic == "שבת"
    assert c.source in ("title", "keyword")


def test_keyword_match():
    c = HybridClassifier().classify(title="נרות חנוכה", artist="להקה")
    assert c.topic == "חנוכה"
    assert c.source == "keyword"


def test_no_match_without_embeddings():
    c = HybridClassifier(embedding_backend=None).classify(title="שיר אקראי לגמרי", artist="")
    assert c.topic is None
    assert c.source == "none"


def test_multiword_keyword():
    c = HybridClassifier().classify(title="לכה דודי לקראת כלה")
    assert c.topic == "שבת"
