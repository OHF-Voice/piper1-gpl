"""Rule-table phonemization for languages that espeak-ng cannot phonemize.

Many languages without a usable espeak-ng voice have a shallow Latin
orthography: one letter or digraph, one sound. isiXhosa (xh) and Sesotho (st)
have no espeak-ng voice at all, and Setswana's (tn) is broken: it emits ``K``,
which is not a phoneme, for ``tlh`` and turns a word-final ``e`` into ``l``
(``gore`` -> ``ɡˈorl``). For such languages a small grapheme table is enough,
so this module is one generic engine plus one JSON table per language, under
``rules/`` in the package. A voice selects it with ``"phoneme_type": "rules"``,
and its ``espeak.voice`` names the table (``"xh"`` loads ``rules/xh.json``).
The espeak voice field is reused as the language key because every voice
config and the training CLI (``--data.espeak_voice``) already carry it.

A table has:

``graphemes``
    grapheme -> IPA. Each word is matched greedily, longest grapheme first, so
    ``ngc`` wins over ``ng`` and ``n``.
``rules`` (optional)
    context rules, tried before ``graphemes`` for the same grapheme, in order:
    ``{"grapheme": "tsh", "left": "n", "ipa": "tʃ"}``. ``left`` is a regular
    expression that must match the text just before the grapheme and
    ``right`` one that must match just after it, both within the word (``^``
    and ``$`` are the word edges). The first rule whose contexts match wins; if
    none does, the plain ``graphemes`` entry applies. A rule may name a
    grapheme that is not in ``graphemes``.
``tones`` (optional)
    ``{"marks": {"\u0301": "4", ...}, "default": "1", "vowels": "aeiou"}``.
    Tone diacritics are taken off the word before matching and written as a
    digit after the grapheme they sat on, using the digits the default id map
    already has and that :mod:`piper.phonemize_thai` and
    :mod:`piper.phonemize_chinese` use: 1 mid, 2 low, 3 falling, 4 high,
    5 rising (:data:`TONE_DIGITS` has the usual marks). ``default`` is the tone
    of an unmarked grapheme from ``vowels`` (Yoruba leaves mid tone unmarked).
    Combining marks that are not tones stay on the letter, so a table can
    still have graphemes such as Setswana ``ê``.
``lexicon`` (optional)
    a ``word<TAB>IPA`` file next to the table. Listed words bypass the rules,
    for languages whose spelling under-determines the sound (Javanese ``e`` is
    /ə/ or /e/). A voice may pass its own with ``lexicon_path``.

Output stays inside :data:`piper.phoneme_ids.DEFAULT_PHONEME_ID_MAP`, so these
voices can warmstart from any IPA base model with no id map change. Tie bars
are removed (affricates are two symbols, as espeak-ng writes them). Digits
cannot be passed through, since they are tone ids here: numbers must be
spelled out before phonemization (``expand_text``), and digits that reach the
phonemizer are dropped with a warning.

The tables were built by copying from orthography2ipa (Apache-2.0), Epitran
(MIT) and the CLDR ``xh-xh_FONIPA`` transform (Unicode License); none of them is
a runtime dependency. See ``rules/SOURCE``.

This code is GPL-3.0 licensed, like the rest of piper1-gpl.
"""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .phoneme_ids import DEFAULT_PHONEME_ID_MAP

_LOGGER = logging.getLogger(__name__)

RULES_DIR = Path(__file__).parent / "rules"

TONE_DIGITS: Mapping[str, str] = {
    "\u0304": "1",  # macron: mid
    "\u0300": "2",  # grave: low
    "\u0302": "3",  # circumflex: falling
    "\u0301": "4",  # acute: high
    "\u030c": "5",  # caron: rising
}
"""Usual tone diacritics -> Thai tone digits. A table lists its own marks; this
is the convention to follow, not a default."""

# Tie bars (above and below) are not in the id map; affricates are written as
# two symbols instead, as espeak-ng does.
_TIE_BARS = str.maketrans("", "", "\u0361\u035c")

# Apostrophe look-alikes, folded to "'" so a table needs only one spelling of
# e.g. Xhosa ng' (the plain velar nasal).
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u02bc": "'", "\u2018": "'"})

# Same convention as phonemize_lithuanian.py (which follows phonemize_espeak.py):
# punctuation a word carries is appended to its phonemes; ". ! ?" also end the
# sentence. Other characters (quotes, brackets, dashes) are dropped.
_KEEP_PUNCT = ".,!?:;"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_WORD_PART_SPLIT = re.compile(r"[-\u2010\u2011\u2013\u2014]+")

Lexicon = Dict[str, str]


@dataclass
class _ContextRule:
    ipa: str
    left: Optional["re.Pattern[str]"]
    right: Optional["re.Pattern[str]"]

    def matches(self, word: str, start: int, end: int) -> bool:
        if (self.left is not None) and (not self.left.search(word[:start])):
            return False
        if (self.right is not None) and (not self.right.match(word[end:])):
            return False
        return True


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


def _clean_ipa(ipa: str) -> str:
    return _nfd(ipa).translate(_TIE_BARS).replace(" ", "")


def resolve_table_path(language: Union[str, Path]) -> Path:
    """Table for a language code ("xh", "xh_ZA", "xh-za") or a path to a table."""
    path = Path(language)
    if path.suffix == ".json":
        if not path.is_file():
            raise FileNotFoundError(f"No rule table at {path}")
        return path

    code = str(language).strip().lower()
    candidates = [code, re.split(r"[-_]", code, maxsplit=1)[0]]
    for candidate in candidates:
        table_path = RULES_DIR / f"{candidate}.json"
        if candidate and table_path.is_file():
            return table_path

    available = ", ".join(sorted(p.stem for p in RULES_DIR.glob("*.json")))
    raise ValueError(
        f"No phoneme rule table for language {language!r} (available: {available})"
    )


def load_lexicon(path: Union[str, Path]) -> Lexicon:
    """word<TAB>IPA  ->  {word: IPA}

    Words are matched lowercased (NFC); spaces in the IPA are ignored. Lines
    starting with # and lines without a tab are skipped."""
    lexicon: Lexicon = {}
    with open(path, "r", encoding="utf-8") as lexicon_file:
        for line in lexicon_file:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
                continue
            word = unicodedata.normalize("NFC", parts[0].strip().lower())
            lexicon[word] = _clean_ipa(parts[1])
    return lexicon


class RuleTable:
    """A language's grapheme table, context rules, tones and lexicon."""

    def __init__(
        self,
        table: Mapping,
        base_dir: Optional[Path] = None,
        lexicon_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self.language: str = table.get("language", "")

        self.graphemes: Dict[str, str] = {
            _nfd(grapheme.lower()): _clean_ipa(ipa)
            for grapheme, ipa in table["graphemes"].items()
        }

        self.rules: Dict[str, List[_ContextRule]] = {}
        for rule in table.get("rules", []):
            grapheme = _nfd(rule["grapheme"].lower())
            left, right = rule.get("left"), rule.get("right")
            self.rules.setdefault(grapheme, []).append(
                _ContextRule(
                    ipa=_clean_ipa(rule["ipa"]),
                    left=re.compile(f"(?:{_nfd(left)})$") if left else None,
                    right=re.compile(_nfd(right)) if right else None,
                )
            )

        self.max_grapheme_length = max(
            len(grapheme) for grapheme in [*self.graphemes, *self.rules]
        )

        tones = table.get("tones") or {}
        self.tone_marks: Dict[str, str] = dict(tones.get("marks", {}))
        self.default_tone: Optional[str] = tones.get("default")
        self.tone_bearing = frozenset(
            _nfd(vowel.lower()) for vowel in tones.get("vowels", [])
        )

        self.lexicon: Lexicon = {}
        if lexicon_path is None and table.get("lexicon") and base_dir is not None:
            lexicon_path = base_dir / table["lexicon"]
        if lexicon_path is not None:
            self.lexicon = load_lexicon(lexicon_path)

    @staticmethod
    def load(
        language: Union[str, Path], lexicon_path: Optional[Union[str, Path]] = None
    ) -> "RuleTable":
        table_path = resolve_table_path(language)
        with open(table_path, "r", encoding="utf-8") as table_file:
            table = json.load(table_file)
        return RuleTable(table, base_dir=table_path.parent, lexicon_path=lexicon_path)

    def symbols(self) -> List[str]:
        """Every phoneme the table can produce (graphemes, rules, tones, lexicon)."""
        outputs = [*self.graphemes.values(), *self.lexicon.values()]
        outputs.extend(rule.ipa for rules in self.rules.values() for rule in rules)
        outputs.extend(self.tone_marks.values())
        if self.default_tone:
            outputs.append(self.default_tone)
        return sorted({symbol for ipa in outputs for symbol in ipa})


class RulesPhonemizer:
    """Phonemize text with a language's grapheme table (see module docstring)."""

    def __init__(
        self,
        language: Union[str, Path],
        lexicon_path: Optional[Union[str, Path]] = None,
        expand_text: Optional[Callable[[str], str]] = None,
    ) -> None:
        """
        :param language: Language code naming a shipped table ("xh", "st",
            "tn"; a region suffix such as "xh_ZA" is ignored) or a path to a
            table of your own.
        :param lexicon_path: Optional word<TAB>IPA file overriding the table's
            own lexicon.
        :param expand_text: Optional text normalizer run before
            phonemization, e.g. to spell out numbers. None of these languages
            has number expansion here, and digits are dropped.
        """
        self.table = RuleTable.load(language, lexicon_path=lexicon_path)
        self.expand_text = expand_text

        unknown = [s for s in self.table.symbols() if s not in DEFAULT_PHONEME_ID_MAP]
        if unknown:
            _LOGGER.warning(
                "Rule table %r produces symbols outside the default phoneme id map "
                "(the voice needs its own map): %s",
                str(language),
                " ".join(unknown),
            )

    def phonemize_word(self, word: str) -> str:
        """One word (letters, combining marks, apostrophes) -> IPA."""
        word = unicodedata.normalize("NFC", word.lower()).translate(_APOSTROPHES)
        lexicon_ipa = self.table.lexicon.get(word)
        if lexicon_ipa is not None:
            return lexicon_ipa

        letters, tones = self._split_tones(_nfd(word))
        return self._match(letters, tones)

    def _split_tones(self, word: str) -> Tuple[str, Dict[int, str]]:
        """Take the table's tone marks off the word.

        Returns the word without them and {index of the base letter the mark
        sat on: tone digit}. Anchoring to the base letter rather than to the
        codepoint just before the mark keeps the tone when another combining
        mark sits between them (ọ́ is o, dot below, acute in NFD)."""
        if not self.table.tone_marks:
            return word, {}

        letters: List[str] = []
        tones: Dict[int, str] = {}
        base: Optional[int] = None
        for char in word:
            tone = self.table.tone_marks.get(char)
            if tone is None:
                if not unicodedata.combining(char):
                    base = len(letters)
                letters.append(char)
            elif base is not None:
                tones[base] = tone
        return "".join(letters), tones

    def _match(self, word: str, tones: Mapping[int, str]) -> str:
        table = self.table
        pieces: List[str] = []
        i = 0
        while i < len(word):
            for length in range(min(table.max_grapheme_length, len(word) - i), 0, -1):
                grapheme = word[i : i + length]
                ipa = self._grapheme_ipa(word, i, grapheme)
                if ipa is not None:
                    break
            else:
                char = word[i]
                if not (unicodedata.combining(char) or char == "'"):
                    # A combining mark no grapheme claims (an accent the
                    # language does not write) is dropped quietly, leaving the
                    # base letter, and so is an apostrophe outside a grapheme
                    # such as ng'; anything else is out of the table.
                    _LOGGER.warning(
                        "Dropping %r: not in the %s rule table (word: %s)",
                        char,
                        table.language,
                        word,
                    )
                i += 1
                continue

            pieces.append(ipa)
            span = range(i, i + length)
            tone = next((tones[j] for j in span if j in tones), None)
            if tone is None and table.default_tone and grapheme in table.tone_bearing:
                tone = table.default_tone
            if tone is not None:
                pieces.append(tone)
            i += length

        return "".join(pieces)

    def _grapheme_ipa(self, word: str, start: int, grapheme: str) -> Optional[str]:
        end = start + len(grapheme)
        for rule in self.table.rules.get(grapheme, ()):
            if rule.matches(word, start, end):
                return rule.ipa
        return self.table.graphemes.get(grapheme)

    def phonemize_sentence(self, sentence: str) -> str:
        pieces: List[str] = []
        for token in sentence.split():
            punct = "".join(c for c in token if c in _KEEP_PUNCT)
            ipa = "".join(
                self.phonemize_word(part)
                for part in _WORD_PART_SPLIT.split(self._word_chars(token))
                if part
            )
            if not ipa:
                if punct and pieces:
                    pieces[-1] += punct
                continue
            pieces.append(ipa + punct)
        return " ".join(pieces)

    def _word_chars(self, token: str) -> str:
        """Letters, combining marks, apostrophes and hyphens of a token."""
        kept: List[str] = []
        dropped_digits = False
        for char in _nfd(token).translate(_APOSTROPHES):
            if (
                char.isalpha()
                or unicodedata.combining(char)
                or char in "'-\u2010\u2011\u2013\u2014"
            ):
                kept.append(char)
            elif char.isdigit():
                dropped_digits = True
        if dropped_digits:
            _LOGGER.warning(
                "Dropping digits from %r: spell out numbers before phonemizing", token
            )
        return "".join(kept)

    def phonemize(self, text: str) -> List[List[str]]:
        """Text -> phonemes (single codepoints, NFD) grouped by sentence."""
        if self.expand_text is not None:
            text = self.expand_text(text)
        result: List[List[str]] = []
        for sentence in _SENTENCE_SPLIT.split(text.strip()):
            if not sentence:
                continue
            ipa = self.phonemize_sentence(sentence)
            if ipa:
                result.append(list(_nfd(ipa)))
        return result


def available_languages() -> Sequence[str]:
    """Language codes with a shipped rule table."""
    return sorted(path.stem for path in RULES_DIR.glob("*.json"))
