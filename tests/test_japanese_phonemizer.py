#!/usr/bin/env python3
"""Tests for Japanese phonemization: OpenJTalk + pitch accent -> IPA."""

import pytest

from piper.config import PhonemeType, PiperConfig
from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP
from piper.phonemize_japanese import (
    ACCENT_FALL,
    ACCENT_PHRASE_BOUNDARY,
    ACCENT_RISE,
    PROSODY_SYMBOLS,
    JapanesePhonemizer,
    missing_phonemes,
)
from piper.voice import PiperVoice

pytest.importorskip("pyopenjtalk", reason="pyopenjtalk-plus is not installed")


@pytest.fixture(scope="module")
def phonemizer() -> JapanesePhonemizer:
    return JapanesePhonemizer()


def _openjtalk(phonemizer: JapanesePhonemizer, text: str) -> str:
    """Readable single-sentence OpenJTalk form, e.g. "a ↓ m e"."""
    sentences = phonemizer.phonemize_openjtalk(text)
    assert len(sentences) == 1, sentences
    return " ".join(sentences[0])


def _segmental(phonemizer: JapanesePhonemizer, text: str) -> str:
    """OpenJTalk phones only, with every prosody symbol stripped."""
    return "".join(
        phone
        for phone in phonemizer.phonemize_openjtalk(text)[0]
        if phone not in PROSODY_SYMBOLS
    )


def test_every_emitted_phoneme_is_in_default_map() -> None:
    """Warmstart compat: nothing this module emits may be outside the IPA map."""
    assert missing_phonemes() == []


def test_phonemes_are_in_default_map(phonemizer: JapanesePhonemizer) -> None:
    text = "今日はいい天気ですね。音楽を聞きたいです。何時に出発しますか？"
    for sentence in phonemizer.phonemize(text):
        for phoneme in sentence:
            assert phoneme in DEFAULT_PHONEME_ID_MAP, repr(phoneme)


def test_kanji_is_read_not_spelled(phonemizer: JapanesePhonemizer) -> None:
    """The reason espeak-ng is unusable: it spells kanji out as letter names."""
    # 東京 -> to-o-kyo-o, identical to the kana spelling.
    assert _segmental(phonemizer, "東京") == "tookyoo"
    assert _segmental(phonemizer, "東京") == _segmental(phonemizer, "とうきょう")
    # 東 alone is "higashi", not "to" — this needs real morphological analysis.
    assert _segmental(phonemizer, "東") == "higashi"


def test_topic_particles(phonemizer: JapanesePhonemizer) -> None:
    """は/へ as particles are wa/e, not ha/he (espeak-ng gets this wrong)."""
    phones = _openjtalk(phonemizer, "私は学校へ行きます").split()
    assert "w" in phones and "a" in phones
    # は read as "ha" would put an 'h' immediately after "watashi"
    assert _openjtalk(phonemizer, "私は").split()[:4] == ["w", "a", ACCENT_RISE, "t"]


def test_accent_minimal_pair(phonemizer: JapanesePhonemizer) -> None:
    """雨 (HL, accented on mora 1) vs 飴 (LH, unaccented)."""
    assert _openjtalk(phonemizer, "雨が降る").startswith(f"a {ACCENT_FALL} m e")
    assert _openjtalk(phonemizer, "飴が好き").startswith(f"a {ACCENT_RISE} m e")


def test_accent_shows_on_following_particle(phonemizer: JapanesePhonemizer) -> None:
    """橋 (LHL) and 端 (LHH) differ only once a particle follows."""
    assert _openjtalk(phonemizer, "橋") == _openjtalk(phonemizer, "端")
    assert ACCENT_FALL in _openjtalk(phonemizer, "橋の")
    assert ACCENT_FALL not in _openjtalk(phonemizer, "端の")


def test_accent_phrase_boundary(phonemizer: JapanesePhonemizer) -> None:
    phones = _openjtalk(phonemizer, "今日はいい天気ですね。")
    assert ACCENT_PHRASE_BOUNDARY in phones


def test_question_vs_statement(phonemizer: JapanesePhonemizer) -> None:
    assert _openjtalk(phonemizer, "そうですか？").endswith("?")
    assert _openjtalk(phonemizer, "そうです。").endswith(".")
    # No punctuation at all still gets a declarative marker.
    assert _openjtalk(phonemizer, "そうです").endswith(".")


def test_numbers_are_expanded(phonemizer: JapanesePhonemizer) -> None:
    """OpenJTalk reads digits natively: 123円 -> hyaku nijuu san en."""
    assert _segmental(phonemizer, "123円") == "hyakunijuusaNeN"


def test_sentence_splitting(phonemizer: JapanesePhonemizer) -> None:
    assert len(phonemizer.phonemize("今日はいい天気ですね。明日は雨です。")) == 2
    assert len(phonemizer.phonemize("えっ、そうですか？やった！")) == 2
    # 、 is a pause inside one sentence, not a split.
    assert len(phonemizer.phonemize("えっ、そうですか？")) == 1


def test_decimal_point_is_not_a_sentence_break(phonemizer: JapanesePhonemizer) -> None:
    assert len(phonemizer.phonemize("1.5リットルの水。")) == 1


def test_devoiced_vowels_folded(phonemizer: JapanesePhonemizer) -> None:
    """です ends in a devoiced u, which folds to plain u by default."""
    assert _openjtalk(phonemizer, "そうです").endswith("d e s u .")

    keep = JapanesePhonemizer(drop_devoiced_vowels=False)
    assert "U" in " ".join(keep.phonemize_openjtalk("そうです")[0])


def test_long_vowels_stay_two_morae(phonemizer: JapanesePhonemizer) -> None:
    """とう is two morae; collapsing it to a length mark loses mora timing."""
    # とうきょう -> t o o ky o o: four 'o', no ː length marks.
    ipa = "".join(phonemizer.phonemize("東京")[0])
    assert ipa.count("o") == 4
    assert "ː" not in ipa


def test_empty_and_punctuation_only(phonemizer: JapanesePhonemizer) -> None:
    assert not phonemizer.phonemize("")
    assert not phonemizer.phonemize("   ")


def test_end_to_end_phonemize_ids() -> None:
    config = PiperConfig(
        num_symbols=256,
        num_speakers=1,
        sample_rate=22050,
        espeak_voice="ja",
        phoneme_id_map=DEFAULT_PHONEME_ID_MAP,
        phoneme_type=PhonemeType.JAPANESE,
    )
    voice = PiperVoice(session=None, config=config)  # type: ignore[arg-type]
    phonemes = voice.phonemize("今日はいい天気ですね。")
    assert phonemes and phonemes[0]
    ids = voice.phonemes_to_ids(phonemes[0])
    assert ids and all(isinstance(i, int) for i in ids)
