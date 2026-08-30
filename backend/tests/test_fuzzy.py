from hamenagen.fuzzy import MatchCandidate, best_match, search


def _library():
    return [
        MatchCandidate(id="1", title="אמת", artist="שמוליק", album="סוכות שמח", filename="emet.mp3"),
        MatchCandidate(id="2", title="מנוחה ושמחה", artist="מקהלה", filename="menucha.mp3"),
        MatchCandidate(id="3", title="הבה נגילה", artist="להקה", filename="hava.mp3"),
        MatchCandidate(id="4", title="ירושלים של זהב", artist="נעמי שמר", filename="yerushalaim.mp3"),
    ]


def test_cross_field_match():
    # "אמת של שמוליק סוכות" — tokens spread across title/artist/album.
    m = best_match("אמת של שמוליק סוכות", _library())
    assert m is not None
    assert m.candidate.id == "1"


def test_underscore_filename_match():
    lib = [MatchCandidate(id="9", title="", filename="שמוליק_סוכות_אמת.mp3")]
    m = best_match("אמת שמוליק סוכות", lib)
    assert m is not None and m.candidate.id == "9"


def test_unrelated_query_returns_nothing():
    assert best_match("קסקסקסקס בלהבלה", _library()) is None


def test_ranking_prefers_better_match():
    results = search("ירושלים של זהב", _library())
    assert results[0].candidate.id == "4"
