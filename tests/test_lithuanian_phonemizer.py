#!/usr/bin/env python3
"""Tests for Lithuanian phonemization: espeak-ng IPA + pitch accent dictionary."""

import unicodedata
from pathlib import Path

import pytest

from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP
from piper.phonemize_lithuanian import (
    ACUTE,
    CIRCUMFLEX,
    DEFAULT_DICTIONARY_PATH,
    DEFAULT_LETTERS_PATH,
    GRAVE,
    LithuanianPhonemizer,
    ipa_vowel_groups,
    letter_ipa,
    load_dictionary,
    load_letters,
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


@pytest.fixture(name="dictionary_path", scope="module")
def dictionary_path_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small dictionary of known entries, so accent placement is tested
    against expected values rather than against the shipped 189k-word file."""
    path = tmp_path_factory.mktemp("lt") / "lt_kirciai.tsv"
    path.write_text(_DICTIONARY, encoding="utf-8")
    return path


@pytest.fixture(name="phonemizer", scope="module")
def phonemizer_fixture(dictionary_path: Path) -> LithuanianPhonemizer:
    return LithuanianPhonemizer(dictionary_path)


# -----------------------------------------------------------------------------
# Dictionary
# -----------------------------------------------------------------------------


def test_dictionary_ships_with_piper() -> None:
    """Package data, like the Hebrew model: pip install, download the voice,
    it works."""
    assert DEFAULT_DICTIONARY_PATH.is_file()
    assert len(load_dictionary(DEFAULT_DICTIONARY_PATH)) > 100_000


def test_default_phonemizer_needs_no_arguments() -> None:
    """The training path and PiperVoice both construct it without a path."""
    ipa = LithuanianPhonemizer().phonemize_word("dabar")
    assert sum(ipa.count(m) for m in (ACUTE, CIRCUMFLEX, GRAVE)) == 1


def test_missing_dictionary_names_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "nera.tsv"
    with pytest.raises(FileNotFoundError, match="nera.tsv"):
        LithuanianPhonemizer(missing)


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "lt_kirciai.tsv"
    path.write_text(
        "# comment\ngeras\t0\t" + ACUTE + "\nbroken line\nzodis\t0\tX\n",
        encoding="utf-8",
    )
    entries = load_dictionary(path)
    assert entries == {"geras": (0, ACUTE)}


def test_fourth_column_overrides_the_group_index(tmp_path: Path) -> None:
    """Where espeak splits a diphthong the dictionary names the IPA group."""
    path = tmp_path / "lt_kirciai.tsv"
    path.write_text("vaikai\t1\t" + CIRCUMFLEX + "\t2\n", encoding="utf-8")
    assert load_dictionary(path) == {"vaikai": (2, CIRCUMFLEX)}


def test_shipped_dictionary_carries_the_diphthong_overrides() -> None:
    """The exception table that used to live in code (11 measured words)."""
    entries = load_dictionary(DEFAULT_DICTIONARY_PATH)
    assert entries["vaikai"] == (2, CIRCUMFLEX)
    assert entries["potencialu"][0] == 4


def test_letter_names_ship_with_piper() -> None:
    letters = load_letters(DEFAULT_LETTERS_PATH)
    assert letters["el"] == ("ˈel̩", ("pašt",))
    assert letters["i"] == ("ˈiː", ())


def test_a_voice_can_bring_its_own_letters(dictionary_path: Path, tmp_path: Path) -> None:
    path = tmp_path / "lt_raides.tsv"
    path.write_text("# own file\nel\tˈeːl\n", encoding="utf-8")
    phonemizer = LithuanianPhonemizer(dictionary_path, letters_path=path)
    assert "".join(phonemizer.phonemize("el")[0]) == "ˈeːl"
    assert letter_ipa("i", letters=phonemizer.letters) is None


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


def test_espeak_s_is_never_retroflex(phonemizer: LithuanianPhonemizer) -> None:
    """espeak emits ʂ for plain "s" in some contexts; the training data has none."""
    for word in ["visi", "senatvės", "rasti", "asmenines"]:
        assert "ʂ" not in phonemizer.phonemize_word(word)


def test_soft_l_is_kept(phonemizer: LithuanianPhonemizer) -> None:
    """ɭ is espeak's soft l, and the trained voice expects it (3117 times in
    the LIEPA data); it must not be swept away together with ʂ."""
    assert "ɭ" in phonemizer.phonemize_word("valdyba")
    assert "ɭ" in phonemizer.phonemize_word("žalias")


def test_espeak_calls_share_the_process_lock() -> None:
    """espeakbridge.set_voice() is process-global, so this phonemizer must take
    the same lock PiperVoice takes around its own espeak calls."""
    from piper import phonemize_espeak, voice

    assert voice._ESPEAK_PHONEMIZER_LOCK is phonemize_espeak.ESPEAK_LOCK


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


def test_expand_text_hook_runs_before_phonemization(dictionary_path: Path) -> None:
    """Number/abbreviation expansion ships with the voice, not with piper."""
    phonemizer = LithuanianPhonemizer(dictionary_path, expand_text=lambda t: "dabar")
    assert phonemizer.phonemize("123") == phonemizer.phonemize("dabar")


# -----------------------------------------------------------------------------
# Phoneme id map
# -----------------------------------------------------------------------------


def test_two_accents_reuse_default_stress_marks() -> None:
    """Only the third accent needs a new symbol; the other two already exist."""
    assert ACUTE in DEFAULT_PHONEME_ID_MAP
    assert CIRCUMFLEX in DEFAULT_PHONEME_ID_MAP
    assert GRAVE not in DEFAULT_PHONEME_ID_MAP


def test_id_166_stays_free_for_the_grave_accent() -> None:
    """Every Lithuanian voice config is the default map plus {ˋ: [166]}, so
    the default map must keep ending at 165."""
    ids = [i for v in DEFAULT_PHONEME_ID_MAP.values() for i in v]
    assert max(ids) == 165
    assert 166 not in ids


def test_espeak_cache_is_bounded(dictionary_path: Path) -> None:
    phonemizer = LithuanianPhonemizer(dictionary_path)
    phonemizer.cache_limit = 2
    for word in ["dabar", "diena", "maistas", "kalbėdamas"]:
        phonemizer.phonemize_word(word)
    assert len(phonemizer._cache) <= 2
