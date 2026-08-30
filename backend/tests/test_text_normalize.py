from hamenagen.text_normalize import normalize, token_set, tokens


def test_separators_collapse():
    assert normalize("שמוליק_סוכות") == normalize("שמוליק סוכות")
    assert normalize("שמוליק  -  סוכות") == "שמוליק סוכות"


def test_final_letters_folded():
    assert normalize("שלום") == normalize("שלוﬦ".replace("ﬦ", "ם"))
    # ן vs נ
    assert normalize("ניגון") == normalize("ניגונ")


def test_niqqud_stripped():
    assert normalize("שַׁבָּת") == "שבת"


def test_token_set_order_independent():
    assert token_set("אמת שמוליק סוכות") == token_set("סוכות אמת שמוליק")


def test_stopwords_dropped():
    assert "official" not in tokens("Song official video")
    assert "mp3" not in tokens("track.mp3")
