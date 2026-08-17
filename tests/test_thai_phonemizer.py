#!/usr/bin/env python3
"""Tests for Thai phonemization: TLTK segmentation + G2P -> IPA + tone digits."""

import pytest

from piper.config import PhonemeType
from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP, phonemes_to_ids
from piper.phonemize_thai import TONES, ThaiPhonemizer

pytest.importorskip("tltk", reason="tltk is not installed")


@pytest.fixture(name="phonemizer", scope="module")
def phonemizer_fixture() -> ThaiPhonemizer:
    return ThaiPhonemizer()


def _one(phonemizer: ThaiPhonemizer, text: str) -> str:
    """Phonemize text that is expected to be a single sentence."""
    sentences = phonemizer.phonemize(text)
    assert len(sentences) == 1, sentences
    return "".join(sentences[0])


# -----------------------------------------------------------------------------
# Tones
# -----------------------------------------------------------------------------


def test_five_tones_are_distinguished(phonemizer: ThaiPhonemizer) -> None:
    """The whole point of not using espeak-ng: espeak collapses all five of
    these to the same phonemes, because a tone mark deletes the vowel."""
    assert _one(phonemizer, "ปา") == "paː1"  # mid
    assert _one(phonemizer, "ป่า") == "paː2"  # low
    assert _one(phonemizer, "ป้า") == "paː3"  # falling
    assert _one(phonemizer, "ป๊า") == "paː4"  # high
    assert _one(phonemizer, "ป๋า") == "paː5"  # rising


def test_tone_minimal_pair(phonemizer: ThaiPhonemizer) -> None:
    assert _one(phonemizer, "ข่าว") == "kʰaːw2"  # news
    assert _one(phonemizer, "ข้าว") == "kʰaːw3"  # rice


def test_every_syllable_carries_a_tone(phonemizer: ThaiPhonemizer) -> None:
    # ประ-เทศ-ไทย-มี-ประ-ชา-กร-เจ็ด-สิบ-ล้าน-คน
    phonemes = phonemizer.phonemize("ประเทศไทยมีประชากรเจ็ดสิบล้านคน")[0]

    # Tones only ever appear at the end of a syllable, so the count of tone
    # digits is the count of syllables.
    assert sum(1 for p in phonemes if p in TONES) == 11


# -----------------------------------------------------------------------------
# Segmentation
# -----------------------------------------------------------------------------


def test_leading_vowels_are_reordered(phonemizer: ThaiPhonemizer) -> None:
    """เ แ โ ใ ไ are written before their consonant but pronounced after it.
    espeak-ng emits them in writing order, e.g. เขา as "e-kha"."""
    assert _one(phonemizer, "เขา") == "kʰaw5"
    assert _one(phonemizer, "ไทย") == "tʰaj1"
    assert _one(phonemizer, "โต") == "toː1"


def test_unspaced_text_is_segmented(phonemizer: ThaiPhonemizer) -> None:
    """Thai is written without spaces, so the G2P has to segment it."""
    assert _one(phonemizer, "สวัสดีครับ") == "sa2wat2diː1kʰrap4"


def test_space_separated_text(phonemizer: ThaiPhonemizer) -> None:
    """Pre-segmented transcripts (the Porjai corpus ships them this way) make
    TLTK raise ValueError if handed over whole, so runs go one at a time."""
    assert _one(phonemizer, "เรา คน นึง ที่ คิด") == "raw1 kʰon1 nɯŋ1 tʰiː3 kʰit4"


def test_silent_final_consonant(phonemizer: ThaiPhonemizer) -> None:
    """การันต์ marks a letter as unpronounced; TLTK leaves an empty syllable."""
    assert _one(phonemizer, "พิมพ์") == "pʰim1"


def test_mai_yamok_repeats_the_word(phonemizer: ThaiPhonemizer) -> None:
    assert _one(phonemizer, "เด็กๆ") == "dek2 dek2"


def test_obsolete_letters(phonemizer: ThaiPhonemizer) -> None:
    """ฃ and ฅ are absent from TLTK's dictionary; both merged into ข and ค."""
    assert _one(phonemizer, "ฃวด") == _one(phonemizer, "ขวด")


def test_decomposed_sara_am(phonemizer: ThaiPhonemizer) -> None:
    """สระอำ typed as nikhahit + sara aa. Unicode gives U+0E33 no canonical
    decomposition, so NFC does not repair it, and TLTK returns an empty
    transcription for the entire run when it sees one. TSync2 contains one.
    """
    assert _one(phonemizer, "นํา") == _one(phonemizer, "นำ")

    # ...including with a tone mark wedged between the two parts.
    assert _one(phonemizer, "ครํ่า") == _one(phonemizer, "คร่ำ") == "kʰram3"


def test_untranscribable_run_is_not_silent(
    phonemizer: ThaiPhonemizer, caplog: pytest.LogCaptureFixture
) -> None:
    """Unspaced Thai is one run per utterance, so an empty transcription costs
    the whole utterance and must never pass unlogged."""
    with caplog.at_level("WARNING"):
        assert not phonemizer.phonemize("กขค")

    assert "No phonemes" in caplog.text


def test_et_cetera_is_read_aloud(phonemizer: ThaiPhonemizer) -> None:
    """ฯลฯ reads as ละ. Stripping the ฯ alone would leave ล to be read."""
    assert _one(phonemizer, "ฯลฯ") == "la4"


# -----------------------------------------------------------------------------
# Numbers
# -----------------------------------------------------------------------------


def test_numbers_are_spelled_out(phonemizer: ThaiPhonemizer) -> None:
    """TLTK does not read numbers -- it transcribes "1250" as "2351"."""
    assert _one(phonemizer, "9") == "kaw3"
    assert _one(phonemizer, "19") == "sip2 kaw3"
    assert _one(phonemizer, "100") == "nɯŋ2 rɔːj4"


def test_thai_digits(phonemizer: ThaiPhonemizer) -> None:
    assert _one(phonemizer, "๑๙") == _one(phonemizer, "19")


def test_grouped_and_decimal_numbers(phonemizer: ThaiPhonemizer) -> None:
    assert _one(phonemizer, "1,250") == _one(phonemizer, "1250")
    assert _one(phonemizer, "3.5") == "saːm5 cut2 haː3"


def test_negative_number(phonemizer: ThaiPhonemizer) -> None:
    assert _one(phonemizer, "-5") == "lop4 haː3"


def test_hyphen_is_not_a_minus_sign(phonemizer: ThaiPhonemizer) -> None:
    assert _one(phonemizer, "โควิด-19") == "kʰoː1wit4-sip2 kaw3"


def test_baht_and_percent(phonemizer: ThaiPhonemizer) -> None:
    assert _one(phonemizer, "฿100").endswith("baːt2")
    assert _one(phonemizer, "25%").endswith("pɤː1sen1")


def test_numbers_can_be_disabled() -> None:
    assert not ThaiPhonemizer(expand_numbers=False).phonemize("19")


# -----------------------------------------------------------------------------
# Structure and robustness
# -----------------------------------------------------------------------------


def test_sentences_are_split_on_terminal_punctuation(
    phonemizer: ThaiPhonemizer,
) -> None:
    sentences = phonemizer.phonemize("สวัสดีครับ. สบายดีไหม? ดีมาก!")
    assert len(sentences) == 3
    assert sentences[0][-1] == "."
    assert sentences[1][-1] == "?"
    assert sentences[2][-1] == "!"


def test_empty_input(phonemizer: ThaiPhonemizer) -> None:
    assert phonemizer.phonemize("") == []
    assert phonemizer.phonemize("   ") == []


def test_non_thai_becomes_a_word_break(phonemizer: ThaiPhonemizer) -> None:
    """Latin text has no Thai pronunciation; it must not reach the id map."""
    assert _one(phonemizer, "เขาบอกว่า OK นะ") == "kʰaw5bɔːk2waː3 na4"


def test_no_leading_or_trailing_word_break(phonemizer: ThaiPhonemizer) -> None:
    phonemes = phonemizer.phonemize("  สวัสดี  ")[0]
    assert phonemes[0] != " "
    assert phonemes[-1] != " "


# -----------------------------------------------------------------------------
# Piper integration
# -----------------------------------------------------------------------------


def test_every_phoneme_has_an_id(phonemizer: ThaiPhonemizer) -> None:
    """The whole inventory must live in the default IPA id map, which is what
    keeps Thai voices warmstartable from the (espeak/IPA) LibriTTS-R base."""
    text = (
        "ประเทศไทยมีประชากรประมาณเจ็ดสิบล้านคน "
        "กรุงเทพมหานครเป็นเมืองหลวง "
        "ข้าว ข่าว เขา ขาว ป่า ป้า ป๊า ป๋า"
    )
    for sentence in phonemizer.phonemize(text):
        for phoneme in sentence:
            assert phoneme in DEFAULT_PHONEME_ID_MAP, phoneme


def test_phonemes_are_single_codepoints(phonemizer: ThaiPhonemizer) -> None:
    """The trainer round-trips phonemes through "".join(), so a multi-character
    phoneme would not survive being written to the cache."""
    for sentence in phonemizer.phonemize("สวัสดีครับ วันนี้อากาศดีมาก"):
        for phoneme in sentence:
            assert len(phoneme) == 1, phoneme


def test_phonemes_to_ids(phonemizer: ThaiPhonemizer) -> None:
    ids = phonemes_to_ids(phonemizer.phonemize("สวัสดีครับ")[0])
    assert ids
    assert max(ids) < 256  # fits the LibriTTS-R base's num_symbols


def test_phoneme_type_is_registered() -> None:
    assert PhonemeType("thai") == PhonemeType.THAI
