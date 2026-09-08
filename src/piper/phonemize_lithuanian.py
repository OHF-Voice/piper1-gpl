"""Lithuanian phonemization: espeak-ng IPA + dictionary-based pitch accent.

espeak-ng's Lithuanian voice produces good phonemes but places stress
incorrectly in roughly half of the words, and it cannot express the three
Lithuanian pitch accents (tvirtapradė / tvirtagalė / trumpinė) at all - it
collapses all of them into a single primary-stress mark. Pitch accent changes
both meaning and pronunciation in Lithuanian (kártas "a time" vs kar̃tas
"bitter"), and it is the main lever for natural-sounding Lithuanian speech.

This phonemizer keeps espeak-ng as the phoneme source (each word is phonemized
separately, so the output is deterministic per word) and then:

1. replaces the ʂ that espeak-ng emits for plain "s" in some contexts
   (visi -> vʲɪʂi) with s. The other retroflex symbol, ɭ, is deliberately
   kept: it is espeak-ng's soft (palatalized) l, the only l it produces
   before front vowels (žalias -> ʒaɭes, valdyba -> vaɭdʲiːba), against the
   syllabic l̩ it uses for the hard l (labas -> l̩abas). In the LIEPA training
   data ɭ appears 3117 times and ʂ never, so a voice trained on it expects
   ɭ and has never seen ʂ; replacing ɭ would merge the two l's the voice
   learned to tell apart;
2. looks the word up in a stress dictionary (word -> vowel group index and
   pitch accent mark) built from the liepa-tts annotated corpus and the
   svogunas/g2p-lt-lexicon pronunciation lexicon, both CC-BY-4.0;
3. moves the stress mark to the syllable that carries the accent, using one
   of three marks: ˈ (tvirtapradė, acute), ˌ (tvirtagalė, circumflex) and
   ˋ (trumpinė, grave; U+02CB, the one symbol added to the default phoneme
   id map - see PHONEME_ID_MAP_NOTE below).

Words missing from the dictionary keep espeak-ng's own stress placement.

Scope (Phase 1): dictionary lookup only, no sentence context. Lithuanian
homographs that differ only in accent (nãmo "of the house" vs namõ
"homewards") cannot be resolved this way; the dictionary holds one entry per
spelling. This is a known and documented limitation, not a bug.

This code is GPL-3.0 licensed, like the rest of piper1-gpl.
"""

import logging
import re
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from .phonemize_espeak import ESPEAK_DATA_DIR, ESPEAK_LOCK, EspeakPhonemizer

_LOGGER = logging.getLogger(__name__)

ESPEAK_VOICE = "lt"

LITHUANIAN_DIR = Path(__file__).parent / "lithuanian"
DEFAULT_DICTIONARY_PATH = LITHUANIAN_DIR / "lt_kirciai.tsv"
"""Stress dictionary shipped with piper as package data, the way the Hebrew
Nakdimon model is: word <TAB> vowel group index <TAB> pitch accent mark
[<TAB> IPA vowel group index]. Built from the liepa-tts corpus annotation and
svogunas/g2p-lt-lexicon, both CC-BY-4.0; see LICENSE and SOURCE in that
directory. The format is documented on load_dictionary()."""

DEFAULT_LETTERS_PATH = LITHUANIAN_DIR / "lt_raides.tsv"
"""Letter names espeak-ng gets wrong when a word is spelled out; see
load_letters(). Both files are data a voice may replace: pass its own paths to
LithuanianPhonemizer instead of patching piper."""

# Pitch accent marks.
ACUTE = "ˈ"        # tvirtapradė (falling), U+02C8 - espeak primary stress
CIRCUMFLEX = "ˌ"   # tvirtagalė (rising), U+02CC - espeak secondary stress
GRAVE = "ˋ"        # trumpinė (short), U+02CB
STRESS_MARKS = ACUTE + CIRCUMFLEX + GRAVE

PHONEME_ID_MAP_NOTE = """
Lithuanian voices use the default phoneme id map with exactly one symbol
appended: ˋ (U+02CB, id 166), the third pitch accent. ˈ (120) and ˌ (121) are
the existing espeak stress marks, reused for the other two accents, and
PAD/BOS/EOS keep their default ids (0/1/2). No existing id is moved, so a
Lithuanian voice config differs from the default map by one entry.
"""

IPA_VOWELS = "aeiouɑɐɔɛɪʊæøɘəɜ"
LENGTH = "ː"
# Symbols that attach to the preceding consonant (palatalization, syllabic l̩).
CONSONANT_MODIFIERS = "ʲʷʰ̩"

_LT_LETTERS = "a-zA-ZąčęėįšųūžĄČĘĖĮŠŲŪŽ"
_WORD_CLEAN = re.compile(f"[^{_LT_LETTERS}0-9]")
_KEEP_PUNCT = ".,!?:;"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

# letter -> (IPA, word prefixes after which it is an abbreviation instead)
Letters = Dict[str, Tuple[str, Tuple[str, ...]]]
_DEFAULT_LETTERS: Optional[Letters] = None


def load_letters(path: Union[str, Path]) -> Letters:
    """letter<TAB>IPA[<TAB>prefix,prefix]  ->  {letter: (IPA, prefixes)}

    Letter names espeak-ng gets wrong when a word is spelled out ("el" is
    expanded to "elektroninis"), and the words after which the same token is a
    real abbreviation rather than a letter ("el. paštas"). Lines starting with
    # are comments; the shipped file explains each entry."""
    letters: Letters = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2 or not parts[1]:
                continue
            prefixes = tuple(p for p in parts[2].split(",") if p) if len(parts) > 2 else ()
            letters[parts[0].lower()] = (parts[1], prefixes)
    return letters


def letter_ipa(word: str, next_word: str = "", letters: Optional[Letters] = None) -> Optional[str]:
    """IPA for a letter name, or None when it is a genuine abbreviation."""
    global _DEFAULT_LETTERS
    if letters is None:
        if _DEFAULT_LETTERS is None:
            _DEFAULT_LETTERS = load_letters(DEFAULT_LETTERS_PATH)
        letters = _DEFAULT_LETTERS
    entry = letters.get(word.lower())
    if entry is None:
        return None
    ipa, prefixes = entry
    for prefix in prefixes:
        if next_word.lower().startswith(prefix):
            return None
    return ipa


def ipa_vowel_groups(ipa: str) -> List[int]:
    """Start index of every vowel group (adjacent vowels + ː form one group)."""
    groups, i = [], 0
    while i < len(ipa):
        if ipa[i] in IPA_VOWELS:
            start = i
            while i + 1 < len(ipa) and (ipa[i + 1] in IPA_VOWELS or ipa[i + 1] == LENGTH):
                i += 1
            groups.append(start)
        i += 1
    return groups


def place_accent(ipa: str, group_index: Optional[int], mark: str) -> str:
    """Remove espeak stress and put `mark` before the syllable of vowel group
    `group_index`. Syllable boundary follows Lithuanian phonotactics:
    V-CV, VC-CV; a word-initial consonant cluster belongs to the first syllable."""
    clean = "".join(c for c in ipa if c not in STRESS_MARKS)
    groups = ipa_vowel_groups(clean)
    if group_index is None or group_index >= len(groups):
        return ipa
    p = groups[group_index]
    i = p - 1
    while i >= 0 and clean[i] in CONSONANT_MODIFIERS:
        i -= 1
    if i >= 0 and clean[i] not in IPA_VOWELS and clean[i] not in " " + LENGTH:
        i -= 1                                   # one consonant
    boundary = i + 1
    j = i
    while j >= 0 and clean[j] not in IPA_VOWELS and clean[j] != " ":
        j -= 1
    if j < 0 or clean[j] == " ":                 # word start
        boundary = j + 1
    return clean[:boundary] + mark + clean[boundary:]


def load_dictionary(path: Union[str, Path]) -> Dict[str, Tuple[int, str]]:
    """word<TAB>vowel group index<TAB>mark[<TAB>IPA group index]
    ->  {word: (group index to accent, mark)}

    The second column counts vowel groups on the letters of the word. That is
    also the vowel group count of espeak-ng's IPA for nearly every word, but
    espeak splits some diphthongs into three sounds ("vaikai" -> vaːjɪkai,
    "asociacijos" -> asoːtsʲijatsʲɪjoːs), and there the letter count points
    one group too early. A pattern fix is unsafe (the same IPA shape is
    legitimate in "apdorojimo", "atnaujintas"), so such words carry an
    optional fourth column with the IPA vowel group index that actually
    holds the accent; when present it is the index returned. Lines starting
    with # and lines that do not fit are skipped."""
    entries: Dict[str, Tuple[int, str]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) not in (3, 4) or parts[2] not in STRESS_MARKS:
                continue
            group = parts[3] if len(parts) == 4 else parts[1]
            entries[parts[0]] = (int(group), parts[2])
    return entries


class LithuanianPhonemizer:
    """Phonemize Lithuanian text using espeak-ng IPA and a stress dictionary."""

    def __init__(
        self,
        dictionary_path: Union[str, Path] = DEFAULT_DICTIONARY_PATH,
        espeak_data_dir: Union[str, Path] = ESPEAK_DATA_DIR,
        expand_text: Optional[Callable[[str], str]] = None,
        letters_path: Union[str, Path] = DEFAULT_LETTERS_PATH,
    ) -> None:
        """
        :param dictionary_path: Stress dictionary (word, vowel group index,
            accent mark). Defaults to the one shipped with piper, so a voice
            needs no extra files; pass another path to override it.
        :param espeak_data_dir: Path to espeak-ng data dir.
        :param letters_path: Letter-name corrections (see load_letters).
            Defaults to the shipped file; a voice may pass its own.
        :param expand_text: Optional text normalizer applied before
            phonemization. Lithuanian number and abbreviation expansion is
            distributed with the voice rather than here, because it is
            orthographic rather than phonemic; without it, digits are read by
            espeak-ng with the wrong case endings.
        """
        self.dictionary = load_dictionary(dictionary_path)
        _LOGGER.debug(
            "Loaded %s dictionary entries from %s", len(self.dictionary), dictionary_path
        )
        self.letters = load_letters(letters_path)
        self.espeak = EspeakPhonemizer(espeak_data_dir)
        self.expand_text = expand_text
        self._cache: Dict[str, str] = {}

    def _espeak_word(self, word: str) -> str:
        ipa = self._cache.get(word)
        if ipa is None:
            # set_voice() is process-global: take the same lock PiperVoice
            # takes, so a Lithuanian voice served beside another cannot race.
            with ESPEAK_LOCK:
                sentences = self.espeak.phonemize(ESPEAK_VOICE, word)
            ipa = "".join("".join(s) for s in sentences).strip()
            # ʂ never occurs in the training data; ɭ (espeak's soft l) is
            # kept on purpose - see the module docstring.
            ipa = ipa.replace("ʂ", "s")
            self._cache[word] = ipa
        return ipa

    def phonemize_word(self, word: str) -> str:
        """One word (letters only) -> IPA with the correct pitch accent."""
        ipa = self._espeak_word(word)
        entry = self.dictionary.get(word.lower())
        if entry is None:
            # Keep espeak's own stress. The in-process espeak leaves
            # monosyllables unstressed; the espeak-ng CLI (used to build the
            # training data) marks them before the vowel - do the same.
            if not any(c in STRESS_MARKS for c in ipa):
                groups = ipa_vowel_groups(ipa)
                if groups:
                    p = groups[0]
                    ipa = ipa[:p] + ACUTE + ipa[p:]
            return ipa
        group_index, mark = entry
        return place_accent(ipa, group_index, mark)

    def phonemize_sentence(self, sentence: str) -> str:
        pieces: List[str] = []
        tokens = sentence.split()
        words = [_WORD_CLEAN.sub("", t) for t in tokens]
        for i, token in enumerate(tokens):
            word = words[i]
            punct = "".join(c for c in token if c in _KEEP_PUNCT)
            if not word:
                if punct and pieces:
                    pieces[-1] += punct
                continue
            override = letter_ipa(
                word, words[i + 1] if i + 1 < len(words) else "", self.letters
            )
            pieces.append((override or self.phonemize_word(word)) + punct)
        return " ".join(pieces)

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
                result.append(list(unicodedata.normalize("NFD", ipa)))
        return result
