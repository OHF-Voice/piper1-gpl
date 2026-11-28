#!/usr/bin/env python3
"""Tests for rule-table phonemization (phoneme_type "rules"): xh, st, tn."""

import json
import unicodedata
from pathlib import Path

import pytest

from piper.config import PhonemeType, PiperConfig
from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP, phonemes_to_ids
from piper.phonemize_rules import (
    RULES_DIR,
    TONE_DIGITS,
    RulesPhonemizer,
    RuleTable,
    available_languages,
    resolve_table_path,
)
from piper.voice import PiperVoice

SHIPPED = ["st", "tn", "xh"]


def _words(language: str, text: str) -> str:
    return RulesPhonemizer(language).phonemize_sentence(text)


def _write_table(tmp_path: Path, table: dict, name: str = "zz.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    return path


# -----------------------------------------------------------------------------
# Shipped tables
# -----------------------------------------------------------------------------


def test_tables_ship_with_piper() -> None:
    assert set(SHIPPED) <= set(available_languages())
    assert (RULES_DIR / "LICENSE").is_file()
    assert (RULES_DIR / "SOURCE").is_file()


@pytest.mark.parametrize("language", SHIPPED)
def test_table_output_is_inside_default_id_map(language: str) -> None:
    """The whole point of the format: no id map change, any IPA warmstart."""
    symbols = RuleTable.load(language).symbols()
    assert symbols
    assert [s for s in symbols if s not in DEFAULT_PHONEME_ID_MAP] == []
    assert "\u0361" not in symbols  # tie bar
    assert "ʼ" not in symbols  # ejective mark: predicted by the spelling


@pytest.mark.parametrize("language", SHIPPED)
def test_every_letter_has_a_mapping(language: str) -> None:
    """Loanwords and names use all of a-z; none may be silently dropped."""
    table = RuleTable.load(language)
    assert [c for c in "abcdefghijklmnopqrstuvwxyz" if c not in table.graphemes] == []


@pytest.mark.parametrize("language", ["xh", "xh_ZA", "xh-za", "XH"])
def test_language_code_with_region(language: str) -> None:
    assert resolve_table_path(language) == RULES_DIR / "xh.json"


def test_unknown_language_lists_the_available_ones() -> None:
    with pytest.raises(ValueError, match="st, tn, xh"):
        RulesPhonemizer("qq")


def test_empty_language_is_an_error() -> None:
    """A voice trained with phoneme_type rules but no --data.espeak_voice."""
    with pytest.raises(ValueError, match="No phoneme rule table"):
        RulesPhonemizer("")


# -----------------------------------------------------------------------------
# isiXhosa
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "ipa"),
    [
        ("molo", "mɔlɔ"),
        ("isiXhosa", "isiǁʰɔsa"),
        ("ibhola", "ibɔla"),  # bh plain b, b implosive
        ("ubaba", "uɓaɓa"),
        ("ucango", "uǀaŋɡɔ"),  # click series: c ch gc nc ngc nkc
        ("chaza", "ǀʰaza"),
        ("gcina", "ɡǀina"),
        ("incoko", "iŋǀɔkɔ"),
        ("iingcango", "iiŋɡǀaŋɡɔ"),
        ("inkcubeko", "iŋkǀuɓɛkɔ"),
        ("iqhina", "iǃʰina"),
        ("inkxaso", "iŋkǁasɔ"),
        ("umhlaba", "umɬaɓa"),  # mhl is m + hl, not mh + l
        ("inhliziyo", "inɬizijɔ"),
        ("umhlophe", "umɬɔpʰɛ"),
        ("isinhanha", "isinɦanɦa"),  # breathy nasal
        ("inyhweba", "iɲɦwɛɓa"),
        ("intliziyo", "intɬizijɔ"),
        ("amandla", "amanɮa"),  # n + dl
        ("ukutya", "ukuca"),
        ("abasetyhini", "aɓasɛcʰini"),
        ("indyebo", "inɟɛɓɔ"),  # n + dy
        ("amagqirha", "amaɡǃixa"),
        ("ikrele", "ikxɛlɛ"),
        ("ihhashe", "iɦaʃɛ"),
        ("ng'ombe", "ŋɔmɓɛ"),  # ng' is the plain velar nasal
        ("ngena", "ŋɡɛna"),
        ("inkosi", "iŋkɔsi"),
        ("inkhosi", "iŋkʰɔsi"),  # n + kh, not nk + h
        ("anchor", "aŋǀʰɔr"),
    ],
)
def test_xhosa_words(word: str, ipa: str) -> None:
    assert RulesPhonemizer("xh").phonemize_word(word) == unicodedata.normalize(
        "NFD", ipa
    )


def test_xhosa_tsh_context_rule() -> None:
    """tsh is ejective after a nasal and aspirated elsewhere (CLDR, NCHLT)."""
    assert _words("xh", "intshaba tshisa") == "intʃaɓa tʃʰisa"


def test_xhosa_apostrophe_variants() -> None:
    phonemizer = RulesPhonemizer("xh")
    for spelling in ("ng'ombe", "ng’ombe", "ngʼombe"):
        assert phonemizer.phonemize_word(spelling) == "ŋɔmɓɛ"


# -----------------------------------------------------------------------------
# Sesotho and Setswana
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ipa"),
    [
        ("Sesotho", "sɪsʊtʰʊ"),
        ("ho hlaha", "hʊ ɬaha"),
        ("tlhaho", "tɬʰahʊ"),
        ("sekgo", "sɪxʊ"),  # kg: velar fricative
        ("lekhokho", "lɪkʰʊkʰʊ"),
        ("ho ja", "hʊ ʒa"),
        ("moriri", "mʊʁiʁi"),
        ("Modimo", "mʊdimʊ"),
        ("ho nka", "hʊ ŋka"),
        ("ntja", "ɲtʃa"),  # homorganic nasal before palatals
        ("nnyeo", "ɲɲɪʊ"),
        ("ho senngwa", "hʊ sɪŋŋwa"),
        ("ho nqosa", "hʊ ŋǃʊsa"),
        ("leqheku", "lɪǃʰɪku"),
        ("ho pjatla", "hʊ pʃatɬa"),
        ("mpjhe", "mpʃʰɪ"),
        ("ho bjarana", "hʊ bʒaʁana"),
        ("ho bofjwa", "hʊ bʊfʃwa"),
    ],
)
def test_sesotho(text: str, ipa: str) -> None:
    assert _words("st", text) == ipa


@pytest.mark.parametrize(
    ("text", "ipa"),
    [
        ("Setswana", "sɪtswana"),
        ("go bua", "χʊ bua"),  # g: uvular fricative
        ("kgosi", "kχʰʊsi"),  # kg: aspirated affricate
        ("botlhe", "bʊtɬʰɪ"),  # espeak-ng: βˈoKl
        ("gore", "χʊrɪ"),  # espeak-ng: ɡˈorl
        ("ntšwa", "ntʃwa"),
        ("motšhini", "mʊtʃʰini"),
        ("mošate", "mʊʃatɪ"),
        ("simologêla", "simʊlʊχɛla"),
        ("qô-qô", "ǃɔǃɔ"),
    ],
)
def test_setswana(text: str, ipa: str) -> None:
    assert _words("tn", text) == unicodedata.normalize("NFD", ipa)


def test_setswana_has_no_letters_espeak_breaks() -> None:
    """espeak-ng tn emits K (not a phoneme) for tlh and l for final e."""
    ipa = _words("tn", "tlhaloganya botlhe gore")
    assert "K" not in ipa
    assert not any(word.endswith("l") for word in ipa.split())


# -----------------------------------------------------------------------------
# Text handling
# -----------------------------------------------------------------------------


def test_sentences_and_punctuation() -> None:
    phonemes = RulesPhonemizer("xh").phonemize("Molo, unjani? Ndiyaphila.")
    assert ["".join(s) for s in phonemes] == ["mɔlɔ, undʒani?", "ndijapʰila."]


def test_output_is_single_codepoints_with_ids() -> None:
    for sentence in RulesPhonemizer("tn").phonemize("Dumela rra! Le kae?"):
        assert all(len(phoneme) == 1 for phoneme in sentence)
        ids = phonemes_to_ids(sentence)
        assert len(ids) == 2 * len(sentence) + 3  # BOS PAD, PAD after each, EOS


def test_digits_are_dropped(caplog: pytest.LogCaptureFixture) -> None:
    """Digits are tone ids; a number must never reach the voice as phonemes."""
    assert _words("xh", "ayi-9 kunye") == "aji kuɲɛ"
    assert "spell out numbers" in caplog.text


def test_hyphenated_word_is_one_word() -> None:
    assert _words("xh", "i-Afrika") == "iafrika"


def test_quotes_and_unknown_accents() -> None:
    """Quotes around a word go; an accent the language does not write leaves
    the base letter (é -> e)."""
    assert _words("st", '"lebésé"') == "lɪbɪsɪ"
    assert _words("st", "'ho ja'") == "hʊ ʒa"


def test_uppercase() -> None:
    assert _words("xh", "EReddersburg") == _words("xh", "ereddersburg")


def test_expand_text() -> None:
    phonemizer = RulesPhonemizer("xh", expand_text=lambda t: t.replace("2", "zimbini"))
    assert phonemizer.phonemize("2") == [list("zimɓini")]


# -----------------------------------------------------------------------------
# Engine features for later languages: context rules, tones, lexicon
# -----------------------------------------------------------------------------


def test_longest_match_and_context_rules(tmp_path: Path) -> None:
    table = {
        "language": "zz",
        "graphemes": {"a": "a", "n": "n", "g": "ɡ", "ng": "ŋ", "s": "s", "e": "e"},
        "rules": [
            {"grapheme": "s", "left": "^", "ipa": "z"},
            {"grapheme": "e", "right": "$", "ipa": "ə"},
            {"grapheme": "nn", "left": "a", "ipa": "ɲ"},  # rule-only grapheme
        ],
    }
    phonemizer = RulesPhonemizer(_write_table(tmp_path, table))
    assert phonemizer.phonemize_word("sangase") == "zaŋasə"
    assert phonemizer.phonemize_word("anna") == "aɲa"
    assert phonemizer.phonemize_word("enna") == "enna"


def test_tone_marks_become_digits(tmp_path: Path) -> None:
    """Yoruba-style: acute high, grave low, unmarked vowel mid; the dot below
    is part of the letter, not a tone, whatever order the marks come in."""
    table = {
        "language": "zz",
        "graphemes": {"o": "o", "ọ": "ɔ", "k": "k", "n": "n", "b": "b"},
        "tones": {
            "marks": {"\u0301": TONE_DIGITS["\u0301"], "\u0300": TONE_DIGITS["\u0300"]},
            "default": "1",
            "vowels": ["o", "ọ"],
        },
    }
    phonemizer = RulesPhonemizer(_write_table(tmp_path, table))
    assert phonemizer.phonemize_word("ọ\u0300kọ\u0301") == "ɔ2kɔ4"
    assert phonemizer.phonemize_word("o\u0301\u0323") == "ɔ4"  # marks unordered
    assert phonemizer.phonemize_word("bo") == "bo1"  # default tone
    assert phonemizer.phonemize_word("ń") == "n4"  # tone on a syllabic nasal


def test_tone_digits_are_thai_convention() -> None:
    assert dict(TONE_DIGITS) == {
        "\u0304": "1",
        "\u0300": "2",
        "\u0302": "3",
        "\u0301": "4",
        "\u030c": "5",
    }


def test_lexicon_overrides_rules(tmp_path: Path) -> None:
    (tmp_path / "zz_lexicon.tsv").write_text(
        "# comment\nkene\tkənɛ\nbroken line\n", encoding="utf-8"
    )
    table = {
        "language": "zz",
        "graphemes": {"k": "k", "e": "e", "n": "n"},
        "lexicon": "zz_lexicon.tsv",
    }
    phonemizer = RulesPhonemizer(_write_table(tmp_path, table))
    assert phonemizer.phonemize_word("Kene") == "kənɛ"
    assert phonemizer.phonemize_word("nene") == "nene"


def test_lexicon_path_argument(tmp_path: Path) -> None:
    lexicon = tmp_path / "xh.tsv"
    lexicon.write_text("molo\tmɔːlɔ\n", encoding="utf-8")
    assert RulesPhonemizer("xh", lexicon_path=lexicon).phonemize_word("molo") == "mɔːlɔ"


def test_tie_bars_are_removed(tmp_path: Path) -> None:
    table = {"language": "zz", "graphemes": {"j": "d\u0361ʒ", "a": "a"}}
    assert RulesPhonemizer(_write_table(tmp_path, table)).phonemize_word("ja") == "dʒa"


def test_symbols_outside_the_map_are_reported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    table = {"language": "zz", "graphemes": {"k": "kʼ", "a": "a"}}
    RulesPhonemizer(_write_table(tmp_path, table))
    assert "outside the default phoneme id map" in caplog.text
    assert "ʼ" in caplog.text


# -----------------------------------------------------------------------------
# Voice
# -----------------------------------------------------------------------------


def test_voice_uses_espeak_voice_as_language() -> None:
    config = PiperConfig(
        num_symbols=256,
        num_speakers=1,
        sample_rate=22050,
        espeak_voice="tn",
        phoneme_id_map=DEFAULT_PHONEME_ID_MAP,
        phoneme_type=PhonemeType.RULES,
    )
    voice = PiperVoice(session=None, config=config)  # type: ignore[arg-type]
    assert ["".join(s) for s in voice.phonemize("Go bua.")] == ["χʊ bua."]
    assert PiperConfig.from_dict(config.to_dict()).phoneme_type == PhonemeType.RULES
