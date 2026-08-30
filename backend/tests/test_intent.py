from hamenagen.intent import Action, parse


def test_topic_request():
    i = parse("תשמיע לי שירים של שבת")
    assert i.action == Action.PLAY_TOPIC
    assert i.topic == "שבת"


def test_recent_downloaded():
    i = parse("תשמיע את השירים האחרונים שהורדתי")
    assert i.action == Action.RECENT_DOWNLOADED


def test_recent_released():
    i = parse("תשמיע את השירים האחרונים שיצאו")
    assert i.action == Action.RECENT_RELEASED


def test_specific_song_search_with_topic_word():
    # Mentions "סוכות" but is clearly a specific-song lookup.
    i = parse("תשמיע אמת של שמוליק סוכות")
    assert i.action == Action.SEARCH_SONG
    assert "אמת" in i.query
    assert i.params.get("topic_hint") == "סוכות"


def test_limit_extraction_digit_and_word():
    assert parse("תשמיע 5 שירים של חנוכה").limit == 5
    assert parse("תשמיע שלושה שירים אקראיים").limit == 3


def test_random():
    assert parse("תשמיע משהו כיף").action == Action.RANDOM
    assert parse("").action == Action.RANDOM
