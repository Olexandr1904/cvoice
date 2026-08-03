import pytest

from cvoice.i18n import REQUIRED_PHRASES, available_languages, load


def test_english_pack_loads():
    pack = load("en")

    assert pack.language == "en"
    assert pack.phrase("waiting")


def test_unknown_language_raises():
    with pytest.raises(LookupError):
        load("kl")


def test_phrase_interpolates_arguments():
    pack = load("en")

    assert "Bash" in pack.phrase("permission.tool", tool="Bash")


def test_missing_placeholder_does_not_crash():
    pack = load("en")

    assert pack.phrase("permission.tool")  # no tool= given


@pytest.mark.parametrize("language", available_languages())
def test_every_pack_has_every_required_phrase(language):
    pack = load(language)

    missing = [key for key in REQUIRED_PHRASES if key not in pack.phrases]
    assert missing == [], f"{language} is missing {missing}"


@pytest.mark.parametrize("language", available_languages())
def test_every_pack_prompt_has_a_text_placeholder(language):
    assert "{text}" in load(language).summary_prompt


def test_english_accepts_english_and_rejects_cyrillic():
    pack = load("en")

    assert pack.matches_language("All tests passed, nothing left to do.") is True
    assert pack.matches_language("Готово, тести зелені") is False


def test_ukrainian_accepts_ukrainian():
    pack = load("uk")

    assert pack.matches_language("Готово, всі тести зелені") is True


def test_ukrainian_rejects_russian_letters():
    pack = load("uk")

    assert pack.matches_language("Готово, все тесты зелёные") is False


def test_ukrainian_rejects_text_with_latin_words():
    pack = load("uk")

    assert pack.matches_language("Готово, виправив SyncManager") is False


def test_ukrainian_pack_carries_a_translit_table():
    pack = load("uk")

    assert pack.translit_table.letters
    assert pack.translit_table.terms


def test_english_pack_needs_no_translit_table():
    assert load("en").translit_table.empty is True


@pytest.mark.parametrize("language", available_languages())
def test_every_pack_declares_voices_for_both_engines(language):
    """A language whose voices are not its own would be read by a foreign voice."""
    pack = load(language)

    assert pack.edge_voice, f"{language} declares no edge voice"
    assert pack.say_voice, f"{language} declares no say voice"


def test_ukrainian_pack_uses_ukrainian_voices():
    pack = load("uk")

    assert pack.edge_voice.startswith("uk-")
    assert pack.say_voice == "Lesya"
