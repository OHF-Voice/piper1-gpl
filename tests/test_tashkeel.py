"""Tests for libtashkeel (Arabic diacritization).

See: https://github.com/mush42/libtashkeel
"""

import unicodedata

import pytest

from piper_tts.tashkeel import ARABIC_DIACRITICS, TashkeelDiacritizer


@pytest.fixture(name="diacritizer", scope="session")
def diacritizer_fixture() -> TashkeelDiacritizer:
    return TashkeelDiacritizer()


@pytest.mark.parametrize(
    ("input_text", "expected_text"),
    (
        (
            ("بسم الله الرحمن الرحيم", "بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيم"),  # from libtashkeel
            ("ذهب الطالب إلى المدرسة", "ذَهَبَ الطَّالِبُ إِلَى الْمَدْرَسَةِ"),  # from ChatGPT
        )
    ),
)
def test_tashkeel(diacritizer, input_text: str, expected_text: str) -> None:
    """Test diacritization."""
    actual_text = diacritizer(input_text, taskeen_threshold=0.8)
    assert normalize(actual_text) == normalize(expected_text)


def normalize(text: str) -> str:
    """Normalize Unicode and strip trailing diacritic if present."""
    text = unicodedata.normalize("NFC", text)
    if text and text[-1] in ARABIC_DIACRITICS:
        text = text[:-1]
    return text
