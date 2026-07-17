#!/usr/bin/env python3
"""Tests for Hebrew phonemization: Nakdimon diacritization + IPA G2P."""

import unicodedata

import pytest

from piper.config import PhonemeType, PiperConfig
from piper.hebrew import NakdimonDiacritizer
from piper.hebrew.hebrew_ipa import hebrew_to_ipa
from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP
from piper.phonemize_hebrew import HebrewPhonemizer
from piper.voice import PiperVoice

# Undotted input -> Nakdimon output. Reference produced by the original model.
_ORACLE = (
    "הכוח לשנות מתחיל ברגע שבו אתה מאמין שזה אפשרי!",
    "הַכּוֹחַ לְשַׁנּוֹת מַתְחִיל בָּרֶגַע שֶׁבּוֹ אַתָּה מַאֲמִין שֶׁזֶּה אֶפְשָׁרִי!",
)


@pytest.fixture(scope="module")
def diacritizer() -> NakdimonDiacritizer:
    return NakdimonDiacritizer()


@pytest.fixture(scope="module")
def phonemizer() -> HebrewPhonemizer:
    return HebrewPhonemizer()


def test_diacritizer_matches_reference(diacritizer: NakdimonDiacritizer) -> None:
    # Compare under NFC: content correctness independent of mark storage order.
    undotted, expected = _ORACLE
    got = diacritizer(undotted)
    assert unicodedata.normalize("NFC", got) == unicodedata.normalize("NFC", expected)


def test_holam_male_is_vowel_not_consonant() -> None:
    """חוֹ (vav carrying holam) is the /o/ vowel, not /v/ (regression)."""
    _, dotted = _ORACLE
    ipa = hebrew_to_ipa(dotted)
    assert "o" in ipa
    # הַכּוֹחַ -> should contain 'ko', never a spurious 'kv'
    assert hebrew_to_ipa("הַכּוֹחַ").count("v") == 0


def test_phonemes_are_in_default_map(phonemizer: HebrewPhonemizer) -> None:
    """Every phoneme must exist in Piper's default IPA map (warmstart compat)."""
    text = "שלום מה שלומך היום. אני רוצה לשמוע מוזיקה"
    for sentence in phonemizer.phonemize(text):
        for phoneme in sentence:
            assert phoneme in DEFAULT_PHONEME_ID_MAP, repr(phoneme)


def test_phonemizer_diacritizes_undotted(phonemizer: HebrewPhonemizer) -> None:
    ipa = "".join("".join(s) for s in phonemizer.phonemize("שלום"))
    assert ipa  # produced phonemes
    assert any(v in ipa for v in "aeiou")  # vowels restored via Nakdimon


def test_phonemizer_preserves_dotted_input(phonemizer: HebrewPhonemizer) -> None:
    """Already-dotted text is not re-diacritized (training transcripts)."""
    _, dotted = _ORACLE
    from_dotted = "".join("".join(s) for s in phonemizer.phonemize(dotted))
    from_undotted = "".join("".join(s) for s in phonemizer.phonemize(_ORACLE[0]))
    assert from_dotted == from_undotted


def test_end_to_end_phonemize_ids() -> None:
    config = PiperConfig(
        num_symbols=256,
        num_speakers=1,
        sample_rate=22050,
        espeak_voice="he",
        phoneme_id_map=DEFAULT_PHONEME_ID_MAP,
        phoneme_type=PhonemeType.HEBREW,
    )
    voice = PiperVoice(session=None, config=config)  # type: ignore[arg-type]
    phonemes = voice.phonemize("שלום מה שלומך היום")
    assert phonemes and phonemes[0]
    ids = voice.phonemes_to_ids(phonemes[0])
    assert ids and all(isinstance(i, int) for i in ids)
