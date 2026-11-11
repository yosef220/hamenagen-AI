"""The knowledge index (1.1): song index, topic lexicon and their place in
the classifier. The synthetic tests pin the behaviour; the last ones check
the data files the app ships."""

import json

import pytest

from hamenagen.classifier import HybridClassifier
from hamenagen.knowledge import (
    LEXICON_FILE,
    SONG_INDEX_FILE,
    SongIndex,
    TopicLexicon,
    features,
    normalize_title,
    title_tokens,
    variants,
)


def test_tokens_drop_niqqud_and_acronym_marks():
    assert title_tokens("שָׁלוֹם עֲלֵיכֶם") == ["שלומ", "עליכמ"]
    assert title_tokens('שירים לל"ג בעומר') == ["שירימ", "ללג", "בעומר"]
    assert title_tokens("Lecha Dodi") == []


def test_prefix_variants_and_pairs():
    assert variants("ובשבת") == ["ובשבת", "בשבת", "שבת"]
    assert variants("שבת") == ["שבת"]  # three letters stay whole
    f = features("פך שמן")
    assert "פכ_שמנ" in f and "שמנ" in f


def test_titles_fold_spellings_and_recording_words():
    assert normalize_title("ברוך א-ל עליון") == normalize_title("ברוך קל עליון")
    assert normalize_title("קה אכסוף") == normalize_title("יה אכסוף")
    assert normalize_title("ה' רועי") == normalize_title("השם רועי")
    assert normalize_title("מעוז צור (לייב)") == normalize_title("מעוז צור")
    assert normalize_title("אלוקים") == normalize_title("אלקים")


INDEX = SongIndex([
    {"title": "יה ריבון עלם ועלמיא", "topics": ["שבת"], "aliases": ["יה ריבון"], "src": ["he.wikipedia"]},
    {"title": "אשת חיל", "topics": ["שבת"], "src": ["he.wikipedia", "sefaria"]},
    {"title": "לשנה הבאה", "topics": ["פסח"], "src": ["sefaria"]},
    {"title": "מעוז צור", "topics": ["חנוכה"], "src": ["he.wikipedia"]},
    {"title": "אוחילה לאל", "topics": ["ראש השנה", "יום כיפור"], "src": ["he.wikipedia"]},
    {"title": "שיר המעלות בשוב", "topics": ["ירושלים"]},
    {"title": "אדיר במלוכה", "topics": ["פסח"]},
    {"title": "אדיר ונאור", "topics": ["יום כיפור"]},
])


def test_index_finds_exact_titles_aliases_and_artist_parts():
    hit = INDEX.lookup("יה ריבון")
    assert hit and hit.topics == ("שבת",) and hit.exact
    assert INDEX.lookup("אברהם פריד - מעוז צור").topics == ("חנוכה",)
    assert INDEX.lookup("", filename="זמירות_-_מעוז_צור.mp3").topics == ("חנוכה",)
    assert INDEX.lookup("", filename="אברהם פריד - מעוז צור.mp3").topics == ("חנוכה",)
    assert INDEX.lookup("אוחילה לאל").topics == ("ראש השנה", "יום כיפור")


def test_index_matches_a_known_name_at_the_start_of_a_title():
    hit = INDEX.lookup("אשת חיל מי ימצא")
    assert hit and hit.topics == ("שבת",) and not hit.exact
    # The title is the start of a longer known name.
    assert INDEX.lookup("יה ריבון עלם").topics == ("שבת",)


def test_prayer_book_section_names_match_only_whole():
    # "לשנה הבאה" closes the Haggadah, but it also opens ordinary phrases.
    assert INDEX.lookup("לשנה הבאה").topics == ("פסח",)
    assert INDEX.lookup("לשנה הבאה בטוב") is None


def test_index_does_not_guess():
    assert INDEX.lookup("שיר חדש") is None
    # "שיר ..." opens many songs: a generic first word never matches as a prefix.
    assert INDEX.lookup("שיר המעלות בשוב ה' את שיבת ציון") is None
    # "אדיר" starts two names with different topics: no decision.
    assert INDEX.lookup("אדיר") is None
    assert INDEX.lookup("") is None


LEXICON = TopicLexicon({
    "חנוכה": {"סופגניות": 0.6, "חמות": 0.05, "נר": 0.3, "שמנ": 0.4},
    "פסח": {"מצה": 0.6, "עבדימ": 0.5, "נר": 0.25},
    "שבת": {"נר": 0.28, "קידוש": 0.5},
}, min_score=0.1, min_margin=0.05)


def test_lexicon_picks_a_topic_only_when_it_is_clearly_ahead():
    r = LEXICON.classify("סופגניות חמות")
    assert r.topic == "חנוכה" and r.margin > 0.5
    assert r.words[0] == "סופגניות"
    # "נר" alone is almost a tie between three topics.
    assert LEXICON.classify("נר").topic is None
    assert LEXICON.classify("שיר בלי מילים מוכרות").topic is None


def test_lexicon_context_counts_less_than_the_title():
    # The album says Pesach, the title says Chanukah: the title wins.
    r = LEXICON.classify("סופגניות", context="מצה")
    assert r.topic == "חנוכה"
    # A neutral title in a Pesach album leans to Pesach.
    assert LEXICON.classify("ניגון", context="עבדים מצה").topic == "פסח"


def test_classifier_layers_and_notes():
    clf = HybridClassifier(None, lexicon=LEXICON, song_index=INDEX)
    # ("יה ריבון" alone is in the curated list; its full name is not.)
    c = clf.classify(title="יה ריבון עלם ועלמיא")
    assert (c.topic, c.source) == ("שבת", "index") and "יה ריבון" in c.note
    # A curated title still comes first.
    assert clf.classify(title="מנוחה ושמחה").source == "title"
    # A keyword comes before the lexicon, and says which word.
    c = clf.classify(title="ריקוד", album="שירי חתונה")
    assert (c.topic, c.source) == ("חתונה", "keyword") and "חתונה" in c.note
    c = clf.classify(title="סופגניות חמות")
    assert (c.topic, c.source) == ("חנוכה", "lexicon") and "סופגניות" in c.note
    # Topics of an index entry beyond the first become tags.
    c = clf.classify(title="אוחילה לאל")
    assert c.topic == "ראש השנה" and "יום כיפור" in c.tags
    assert clf.classify(title="שיר חדש").topic is None


# -------------------------------------------------------------- the shipped data
needs_data = pytest.mark.skipif(not (SONG_INDEX_FILE.exists() and LEXICON_FILE.exists()),
                                reason="knowledge files not built")


@needs_data
def test_shipped_files_carry_their_licence_and_sources():
    lex = json.loads(LEXICON_FILE.read_text(encoding="utf-8"))
    idx = json.loads(SONG_INDEX_FILE.read_text(encoding="utf-8"))
    for data in (lex, idx):
        assert data["licence"] == "CC BY-SA 4.0" and "Wikipedia" in data["attribution"]
    assert {s["source"] for s in lex["sources"]} >= {"he.wikipedia", "sefaria"}
    for s in lex["sources"]:
        assert s["licence"].lower() in {"cc by-sa 4.0", "public domain", "pd", "cc0", "cc-by", "cc-by-sa"}
    assert len(lex["topics"]) == 13 and len(idx["entries"]) > 300


@needs_data
@pytest.mark.parametrize("title,topic", [
    ("יה ריבון", "שבת"),
    ("צור משלו", "שבת"),
    ("מעוז צור", "חנוכה"),
    ("חד גדיא", "פסח"),
    ("עבדים היינו", "פסח"),
    ("אקדמות", "שבועות"),
    ("שושנת יעקב", "פורים"),
])
def test_shipped_index_knows_classic_songs(title, topic):
    hit = SongIndex.load().lookup(title)
    assert hit is not None and hit.topics[0] == topic


@needs_data
@pytest.mark.parametrize("title,topic", [
    ("נרות דולקים", "חנוכה"),
    ("מצה ומרור", "פסח"),
    ("שעיר לעזאזל", "יום כיפור"),
    ("משלוח מנות", "פורים"),
    ("ארבעת המינים", "סוכות"),
])
def test_shipped_lexicon_places_descriptive_titles(title, topic):
    assert TopicLexicon.load().classify(title).topic == topic


@needs_data
@pytest.mark.parametrize("title", ["אבא", "תודה", "הלב שלי", "שיר רגיל", "ניגון"])
def test_shipped_lexicon_leaves_ordinary_titles_alone(title):
    assert TopicLexicon.load().classify(title).topic is None
