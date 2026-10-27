#!/usr/bin/env python3
"""Tests for Hebrew phonemization: renikud G2P (text -> stressed IPA)."""

import unicodedata

import pytest

from piper.config import PhonemeType, PiperConfig
from piper.hebrew import RenikudG2P
from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP
from piper.phonemize_hebrew import HebrewPhonemizer
from piper.voice import PiperVoice

# Undotted input -> IPA. References produced by the original renikud-onnx package.
_ORACLE = [
    (
        "הכוח לשנות מתחיל ברגע שבו אתה מאמין שזה אפשרי!",
        "hakˈoaχ leʃanˈot matχˈil baʁˈeɡa ʃebˈo ʔatˈa maʔamˈin ʃezˈe ʔefʃaʁˈi!",
    ),
    ("צ'יפס וג'ירפה", "tʃˈips vedʒiʁafˈa"),
    ("שלום, מה שלומך? Classiq 2026.", "ʃelˈom, mˈa ʃlomχˈa? Classiq 2026."),
]


@pytest.fixture(name="g2p", scope="module")
def g2p_fixture() -> RenikudG2P:
    return RenikudG2P()


@pytest.fixture(name="phonemizer", scope="module")
def phonemizer_fixture() -> HebrewPhonemizer:
    return HebrewPhonemizer()


@pytest.mark.parametrize("text,expected", _ORACLE)
def test_g2p_matches_reference(g2p: RenikudG2P, text: str, expected: str) -> None:
    assert unicodedata.normalize("NFC", g2p(text)) == unicodedata.normalize(
        "NFC", expected
    )


def test_one_stress_per_hebrew_word(g2p: RenikudG2P) -> None:
    ipa = g2p("אני רוצה לשמוע מוזיקה")
    assert [w.count("ˈ") for w in ipa.split()] == [1, 1, 1, 1]


def test_phonemes_are_in_default_map(phonemizer: HebrewPhonemizer) -> None:
    """Every phoneme must exist in Piper's default IPA map (warmstart compat)."""
    text = "שלום מה שלומך היום. אני רוצה לשמוע מוזיקה"
    for sentence in phonemizer.phonemize(text):
        for phoneme in sentence:
            assert phoneme in DEFAULT_PHONEME_ID_MAP, repr(phoneme)


def test_phonemizer_strips_niqqud(phonemizer: HebrewPhonemizer) -> None:
    """Dotted text (e.g. training transcripts) phonemizes like its undotted form."""
    dotted = "הַכּוֹחַ לְשַׁנּוֹת מַתְחִיל בָּרֶגַע"
    undotted = "הכוח לשנות מתחיל ברגע"
    assert phonemizer.phonemize(dotted) == phonemizer.phonemize(undotted)


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
