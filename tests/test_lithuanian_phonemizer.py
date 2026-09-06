#!/usr/bin/env python3
"""Tests for Lithuanian phonemization: espeak-ng IPA + pitch accent dictionary."""

import unicodedata
from pathlib import Path

import pytest

from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP
from piper.phonemize_lithuanian import (
    ACUTE,
    CIRCUMFLEX,
    DICTIONARY_NAME,
    GRAVE,
    LithuanianPhonemizer,
    find_dictionary,
    ipa_vowel_groups,
    letter_ipa,
    load_dictionary,
    place_accent,
)

# word <TAB> vowel group index <TAB> pitch accent mark
_DICTIONARY = "\n".join(
    [
        "dabar\t1\t" + CIRCUMFLEX,  # dabar̃, accent on the second group
        "maistas\t0\t" + CIRCUMFLEX,  # maĩstas, on the diphthong "ai"
        "diena\t1\t" + GRAVE,  # dienà, short accent on the ending
        "kalbėdamas\t1\t" + ACUTE,  # kalbė́damas
    ]
)


@pytest.fixture(name="data_dir", scope="module")
def data_dir_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A voice directory with the dictionary in <data_dir>/lithuanian/."""
    data_dir = tmp_path_factory.mktemp("lt_voice")
    lithuanian_dir = data_dir / "lithuanian"
    lithuanian_dir.mkdir()
    (lithuanian_dir / DICTIONARY_NAME).write_text(_DICTIONARY, encoding="utf-8")
    return data_dir


@pytest.fixture(name="phonemizer", scope="module")
def phonemizer_fixture(data_dir: Path) -> LithuanianPhonemizer:
    return LithuanianPhonemizer(data_dir)


# -----------------------------------------------------------------------------
# Dictionary lookup
# -----------------------------------------------------------------------------


def test_dictionary_found_in_subdirectory(data_dir: Path) -> None:
    assert find_dictionary([data_dir]) == data_dir / "lithuanian" / DICTIONARY_NAME


def test_dictionary_found_in_data_dir_root(tmp_path: Path) -> None:
    """<data_dir>/<name> is the fallback, as with g2pW data."""
    (tmp_path / DICTIONARY_NAME).write_text(_DICTIONARY, encoding="utf-8")
    assert find_dictionary([tmp_path]) == tmp_path / DICTIONARY_NAME


def test_missing_dictionary_says_where_it_looked(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as err:
        find_dictionary([tmp_path])
    assert DICTIONARY_NAME in str(err.value)
    assert str(tmp_path) in str(err.value)


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / DICTIONARY_NAME
    path.write_text(
        "geras\t0\t" + ACUTE + "\nbroken line\nzodis\t0\tX\n", encoding="utf-8"
    )
    entries = load_dictionary(path)
    assert entries == {"geras": (0, ACUTE)}


# -----------------------------------------------------------------------------
# Accent placement
# -----------------------------------------------------------------------------


def test_vowel_groups_treat_adjacent_vowels_as_one() -> None:
    # "ai" is one group, and length marks belong to the group before them.
    assert len(ipa_vowel_groups("maistas")) == 2
    assert len(ipa_vowel_groups("moːtʲerʲis")) == 3


def test_accent_goes_before_the_syllable_not_the_vowel() -> None:
    """Lithuanian syllable boundary: V-CV, so the mark precedes the consonant."""
    assert place_accent("dabar", 1, CIRCUMFLEX) == "daˌbar"


def test_word_initial_cluster_stays_in_the_first_syllable() -> None:
    assert place_accent("kalbeedamas", 0, ACUTE) == "ˈkalbeedamas"


def test_existing_espeak_stress_is_replaced_not_added(
    phonemizer: LithuanianPhonemizer,
) -> None:
    ipa = phonemizer.phonemize_word("dabar")
    assert ipa.count(ACUTE) + ipa.count(CIRCUMFLEX) + ipa.count(GRAVE) == 1


def test_all_three_accents_are_produced(phonemizer: LithuanianPhonemizer) -> None:
    assert CIRCUMFLEX in phonemizer.phonemize_word("maistas")
    assert GRAVE in phonemizer.phonemize_word("diena")
    assert ACUTE in phonemizer.phonemize_word("kalbėdamas")


def test_unknown_word_keeps_espeak_stress(phonemizer: LithuanianPhonemizer) -> None:
    """Words outside the dictionary must still come out stressed exactly once."""
    ipa = phonemizer.phonemize_word("nesamas")
    assert sum(ipa.count(m) for m in (ACUTE, CIRCUMFLEX, GRAVE)) == 1


# -----------------------------------------------------------------------------
# Lithuanian-specific espeak corrections
# -----------------------------------------------------------------------------


def test_no_retroflex_consonants(phonemizer: LithuanianPhonemizer) -> None:
    """espeak emits ʂ for plain "s" in some contexts; Lithuanian has none."""
    for word in ["visi", "senatvės", "rasti", "asmenines"]:
        assert "ʂ" not in phonemizer.phonemize_word(word)


def test_letter_l_is_not_read_as_a_word() -> None:
    """espeak expands "el" to "elektroninis", which broke every abbreviation
    containing L (LRT, MTL)."""
    assert letter_ipa("el") == "ˈel̩"


def test_the_abbreviation_keeps_its_expansion() -> None:
    """"el. paštas" (e-mail) is a real abbreviation, not the letter L."""
    assert letter_ipa("el", "paštas") is None


# -----------------------------------------------------------------------------
# Output shape
# -----------------------------------------------------------------------------


def test_phonemize_returns_one_list_per_sentence(
    phonemizer: LithuanianPhonemizer,
) -> None:
    result = phonemizer.phonemize("Diena. Dabar!")
    assert len(result) == 2
    assert all(isinstance(sentence, list) for sentence in result)


def test_phonemes_are_single_codepoints_in_nfd(
    phonemizer: LithuanianPhonemizer,
) -> None:
    for sentence in phonemizer.phonemize("Kalbėdamas dabar."):
        assert all(len(p) == 1 for p in sentence)
        assert "".join(sentence) == unicodedata.normalize("NFD", "".join(sentence))


def test_punctuation_is_kept(phonemizer: LithuanianPhonemizer) -> None:
    assert "?" in "".join(phonemizer.phonemize("Dabar?")[0])


def test_expand_text_hook_runs_before_phonemization(data_dir: Path) -> None:
    """Number/abbreviation expansion ships with the voice, not with piper."""
    phonemizer = LithuanianPhonemizer(data_dir, expand_text=lambda t: "dabar")
    assert phonemizer.phonemize("123") == phonemizer.phonemize("dabar")


# -----------------------------------------------------------------------------
# Phoneme id map
# -----------------------------------------------------------------------------


def test_two_accents_reuse_default_stress_marks() -> None:
    """Only the third accent needs a new symbol; the other two already exist."""
    assert ACUTE in DEFAULT_PHONEME_ID_MAP
    assert CIRCUMFLEX in DEFAULT_PHONEME_ID_MAP
    assert GRAVE not in DEFAULT_PHONEME_ID_MAP
