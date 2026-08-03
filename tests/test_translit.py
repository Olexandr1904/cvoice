from claude_voice.speech.translit import Table, has_latin_words, transliterate

TABLE = Table(
    terms={
        "pull request": "пул реквест",
        "manager": "менеджер",
        "login": "логін",
        "api": "апі",
        "sync": "синк",
    },
    digraphs=[("sh", "ш"), ("ch", "ч"), ("ck", "к")],
    letters={
        "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "ґ", "h": "г",
        "i": "і", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
        "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
        "y": "й", "z": "з",
    },
)


def test_text_without_latin_is_unchanged():
    assert transliterate("Готово, тести зелені.", TABLE) == "Готово, тести зелені."


def test_known_term_uses_the_dictionary():
    assert transliterate("Відкрив pull request", TABLE) == "Відкрив пул реквест"


def test_multiword_term_wins_over_its_parts():
    result = transliterate("pull request", TABLE)

    assert result == "пул реквест"


def test_unknown_word_is_transliterated_phonetically():
    assert transliterate("blob", TABLE) == "блоб"


def test_camel_case_is_split_into_words():
    assert transliterate("SyncManager", TABLE) == "синк менеджер"


def test_short_acronym_is_spelled_out():
    assert transliterate("URL", TABLE) == "у-р-л"


def test_known_acronym_beats_spelling_it_out():
    assert transliterate("API", TABLE) == "апі"


def test_matching_is_case_insensitive():
    assert transliterate("Login", TABLE) == "логін"


def test_has_latin_words_ignores_short_fragments():
    assert has_latin_words("Готово, все ок") is False
    assert has_latin_words("Готово, SyncManager") is True
