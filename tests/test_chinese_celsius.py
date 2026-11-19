"""Celsius temperatures keep the whole number, including the fraction."""

import pytest

phonemize_chinese = pytest.importorskip("piper.phonemize_chinese")
ChinesePhonemizer = phonemize_chinese.ChinesePhonemizer


def test_decimal_celsius_keeps_the_whole_number() -> None:
    from unicode_rbnf import RbnfEngine

    phonemizer = ChinesePhonemizer.__new__(ChinesePhonemizer)
    phonemizer.number_engine = RbnfEngine.for_language("zh")

    assert phonemizer._numbers_to_words("现在是7.5°C。") == "现在是七点五度。"
    assert phonemizer._numbers_to_words("现在是-7.5°C。") == "现在是零下七点五度。"
    assert phonemizer._numbers_to_words("现在是−3.5°C。") == "现在是零下三点五度。"
    assert phonemizer._numbers_to_words("现在是98.6 °C。") == "现在是九十八点六度。"
    assert (
        phonemizer._numbers_to_words("面积是12.5平方米，温度是7.5°C。")
        == "面积是十二点五平方米，温度是七点五度。"
    )
    # Integers stay on the same path.
    assert phonemizer._numbers_to_words("现在是7°C。") == "现在是七度。"
    assert phonemizer._numbers_to_words("现在是-7°C。") == "现在是零下七度。"
    assert phonemizer._numbers_to_words("现在是7℃。") == "现在是七度。"
