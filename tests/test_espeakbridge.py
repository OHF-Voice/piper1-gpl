import pytest

from piper import espeakbridge

terminator_tests = [
    # exact matches for punctuation are retained verbatim
    (
        "en-us",
        "Hello, world! Colons: important? Maybe; maybe not.",
        [",", "!", ":", "?", ";", "."],
    ),
    # ellipses get normalized to semicolons
    ("en-us", "An ellipsis… Could it be true?", [";", "?"]),
    ("en-us", "An ASCII ellipsis... Could it be true?", [";", "?"]),
    ("en-us", "A long ellipsis.... Could it be true?", [";", "?"]),
    # em dashes get normalized to semicolons
    ("en-us", "Em dashes — for all your punctuation needs.", [";", "."]),
    # various Chinese punctuation gets normalized to ASCII equivalents
    (
        "cmn",
        "你好，世界！省略号……一、二，三。问号？",
        [",", "!", ";", ",", ",", ".", "?"],
    ),
]


@pytest.mark.parametrize("locale,text,expect", terminator_tests)
def test_get_phonemes_terminator(locale: str, text: str, expect: list[str]):
    espeakbridge.set_voice(locale)

    result = espeakbridge.get_phonemes(text)

    assert [result[i][1] for i in range(len(result)) if result[i][1]] == expect
