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


def test_listening_habits():
    assert parse("השירים שאהבתי").action == Action.FAVORITES
    assert parse("המועדפים שלי").action == Action.FAVORITES
    assert parse("מה ששמעתי לאחרונה").action == Action.HISTORY
    assert parse("השירים שאני הכי שומע").action == Action.MOST_PLAYED
    assert parse("השירים שאני הכי שומעת").action == Action.MOST_PLAYED


def test_span_of_time():
    i = parse("שעה של שירי שבת")
    assert (i.action, i.topic, i.minutes, i.limit) == (Action.PLAY_TOPIC, "שבת", 60, None)
    assert parse("חצי שעה של מוזיקה").action == Action.RANDOM
    assert parse("חצי שעה של מוזיקה").minutes == 30
    assert parse("20 דקות של שירי חנוכה").minutes == 20
    assert parse("עשרים דקות של שירי חנוכה").minutes == 20
    assert parse("שעתיים של שירי חתונה").minutes == 120
    assert parse("שעה וחצי של שירים אקראיים").minutes == 90


def test_hebrew_prefixes_and_acronyms():
    assert parse("תשמיע לי שירים לשבת").topic == "שבת"
    assert parse('שירים לל"ג בעומר').topic == "ל״ג בעומר"
    assert parse("מוזיקה ווקאלית").topic == "ווקאלי"


def test_one_extra_word_may_name_a_song():
    i = parse("ירושלים של זהב")
    assert i.action == Action.PLAY_TOPIC and i.topic == "ירושלים"
    assert i.params["song_query"]  # the service checks for a song by that name first
