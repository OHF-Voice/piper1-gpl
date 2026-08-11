"""Japanese phonemization: OpenJTalk full-context labels -> IPA + prosody symbols.

espeak-ng's Japanese voice has no kanji coverage at all: it falls back to reading
Unicode character names, so 今日 becomes the phonemes for "Chinese letter"
(twice). It also mis-reads the topic particles は/へ as "ha"/"he" even for
kana-only input, and it carries no pitch accent. Instead we use OpenJTalk
(pyopenjtalk), which does full morphological analysis and gives correct readings
plus accent information.

Pitch accent is the dominant naturalness lever in Japanese TTS, so we don't stop
at segmental phonemes. OpenJTalk's full-context labels are parsed into the
accent-annotated form used by ESPnet's `pyopenjtalk_prosody` G2P, then mapped to
IPA so the output uses Piper's default phoneme id map. That keeps Japanese voices
compatible with the IPA-based (espeak) warmstart, the same trick
:mod:`piper.phonemize_hebrew` uses.

Prosody symbols (all present in the default id map):

- ``↑``  accent rise (low -> high, within an accent phrase)
- ``↓``  accent fall (the accent nucleus)
- ``#``  accent phrase boundary
- ``,``  pause (OpenJTalk ``pau``, e.g. from 、)
- ``.``  end of a declarative sentence
- ``?``  end of an interrogative sentence

ESPnet spells the last three ``_``, ``$`` and ``?``. We avoid ``_`` and ``$``
because Piper reserves them for padding and end-of-sentence
(see :mod:`piper.const`).
"""

import logging
import re
from typing import Dict, List, Optional, Sequence

_LOGGER = logging.getLogger(__name__)

# Prosody symbols. Chosen so they already have ids in DEFAULT_PHONEME_ID_MAP.
ACCENT_RISE = "↑"
ACCENT_FALL = "↓"
ACCENT_PHRASE_BOUNDARY = "#"
PAUSE = ","
DECLARATIVE_END = "."
INTERROGATIVE_END = "?"

PROSODY_SYMBOLS = frozenset(
    {
        ACCENT_RISE,
        ACCENT_FALL,
        ACCENT_PHRASE_BOUNDARY,
        PAUSE,
        DECLARATIVE_END,
        INTERROGATIVE_END,
    }
)

# OpenJTalk phone -> IPA. Palatalized consonants uniformly use ʲ rather than
# their closest single-symbol equivalents (ny -> nʲ, not ɲ) to keep the series
# consistent. Long vowels stay as two identical vowels because Japanese counts
# them as two morae, and mora timing is what the duration predictor should see.
OPENJTALK_TO_IPA: Dict[str, str] = {
    # Vowels
    "a": "a",
    "i": "i",
    "u": "ɯ",  # compressed close back unrounded, not [u]
    "e": "e",
    "o": "o",
    # Consonants
    "k": "k",
    "ky": "kʲ",  # キャ
    "kw": "kʷ",  # クヮ
    "g": "ɡ",
    "gy": "ɡʲ",  # ギャ
    "gw": "ɡʷ",  # グヮ
    "s": "s",
    "sh": "ɕ",  # シ
    "z": "z",
    "j": "dʑ",  # ジャ
    "t": "t",
    "ts": "ts",  # ツ
    "ty": "tʲ",  # テャ
    "ch": "tɕ",  # チ
    "d": "d",
    "dy": "dʲ",  # デャ
    "n": "n",
    "ny": "nʲ",  # ニャ
    "h": "h",
    "hy": "hʲ",  # ヒャ
    "f": "ɸ",  # フ
    "b": "b",
    "by": "bʲ",  # ビャ
    "p": "p",
    "py": "pʲ",  # ピャ
    "m": "m",
    "my": "mʲ",  # ミャ
    "y": "j",  # ヤ
    "r": "ɾ",
    "ry": "ɾʲ",  # リャ
    "w": "w",
    "v": "v",  # ヴ
    # Specials
    "N": "ɴ",  # ん (moraic nasal)
    "cl": "ʔ",  # っ (geminate closure)
}

# OpenJTalk marks devoiced vowels with an uppercase letter (desU = です).
DEVOICED_VOWELS = frozenset({"A", "I", "U", "E", "O"})

# Vowels and moraic phones that can carry an accent phrase boundary.
_MORA_FINAL_PHONES = frozenset(
    {"a", "i", "u", "e", "o", "A", "I", "U", "E", "O", "N", "cl"}
)

# Sentence-final punctuation, taking any trailing closing brackets/quotes and
# whitespace with it. OpenJTalk itself only turns these into a `pau`, so we split
# first to get one audio chunk per sentence.
_SENTENCE_END_PATTERN = re.compile(r"[。．！？!?]+[」』）】〉》”’\"')\]\s]*")

_CURRENT_PHONE_PATTERN = re.compile(r"\-(.*?)\+")

# "no match" sentinel for the numeric label fields, matching ESPnet's choice.
_NO_FEATURE = -50


class JapanesePhonemizer:
    """Phonemize Japanese text with OpenJTalk, including pitch accent."""

    def __init__(
        self,
        drop_devoiced_vowels: bool = True,
        use_marine: bool = False,
    ) -> None:
        """Initialize phonemizer.

        :param drop_devoiced_vowels: Fold OpenJTalk's devoiced vowels (A I U E O)
            into their voiced counterparts. Devoicing is largely predictable from
            context, so keeping it mainly enlarges the phoneme inventory.
        :param use_marine: Use the neural `marine` model to estimate accent
            instead of OpenJTalk's rules. More accurate on compound words, but
            requires ``pip install marine``.
        """
        import pyopenjtalk

        self.pyopenjtalk = pyopenjtalk
        self.drop_devoiced_vowels = drop_devoiced_vowels
        self.use_marine = use_marine

        if use_marine:
            try:
                pyopenjtalk.load_marine_model()
            except Exception as exc:  # pragma: no cover
                raise RuntimeError(
                    "Failed to load the marine accent model. "
                    "Install it with 'pip install marine'."
                ) from exc

    def phonemize(self, text: str) -> List[List[str]]:
        """Return IPA phonemes with prosody symbols, grouped by sentence.

        Each phoneme is a single codepoint, matching how espeak phonemes are
        keyed in :data:`piper.phoneme_ids.DEFAULT_PHONEME_ID_MAP`.
        """
        all_phonemes: List[List[str]] = []

        for sentence_phones in self.phonemize_openjtalk(text):
            ipa_phonemes: List[str] = []

            for phone in sentence_phones:
                if phone in PROSODY_SYMBOLS:
                    ipa_phonemes.append(phone)
                    continue

                ipa = OPENJTALK_TO_IPA.get(phone)
                if ipa is None:
                    _LOGGER.warning("No IPA mapping for OpenJTalk phone: %s", phone)
                    continue

                # Multi-symbol IPA (kʲ, tɕ, dʑ, ...) becomes separate phonemes.
                ipa_phonemes.extend(ipa)

            if ipa_phonemes:
                all_phonemes.append(ipa_phonemes)

        return all_phonemes

    def phonemize_openjtalk(self, text: str) -> List[List[str]]:
        """Return OpenJTalk phones with prosody symbols, grouped by sentence.

        This is the intermediate representation, before the IPA mapping. It is
        the readable form ("ky o o ↑ w a ..."), useful for inspecting accent
        placement.
        """
        return [
            phones
            for sentence in _split_sentences(text)
            if (phones := self._phonemize_sentence(sentence))
        ]

    def _phonemize_sentence(self, sentence: str) -> List[str]:
        """Parse one sentence's full-context labels into phones + prosody."""
        try:
            if self.use_marine:
                njd_features = self.pyopenjtalk.run_frontend(sentence, run_marine=True)
            else:
                njd_features = self.pyopenjtalk.run_frontend(sentence)

            labels = self.pyopenjtalk.make_label(njd_features)
        except Exception:
            _LOGGER.exception("Failed to phonemize sentence: %s", sentence)
            return []

        num_labels = len(labels)
        phones: List[str] = []

        for label_idx, label in enumerate(labels):
            match = _CURRENT_PHONE_PATTERN.search(label)
            if match is None:
                continue

            phone = match.group(1)
            if self.drop_devoiced_vowels and (phone in DEVOICED_VOWELS):
                phone = phone.lower()

            if phone == "sil":
                # Utterance boundary. The leading one needs no symbol (Piper
                # prepends BOS itself); the trailing one carries the intonation.
                if label_idx == (num_labels - 1):
                    # E:<f1>_<f2>!<e3>_... where e3 == 1 marks a question.
                    is_question = _numeric_feature(r"!(\d+)_", label) == 1
                    phones.append(INTERROGATIVE_END if is_question else DECLARATIVE_END)

                continue

            if phone == "pau":
                phones.append(PAUSE)
                continue

            phones.append(phone)

            if label_idx >= (num_labels - 1):
                # No following label to compare accent position against.
                continue

            # A: mora position within the accent phrase, relative to the accent
            # nucleus. a1 == 0 means this mora *is* the nucleus.
            a1 = _numeric_feature(r"/A:([0-9\-]+)\+", label)
            a2 = _numeric_feature(r"\+(\d+)\+", label)
            a3 = _numeric_feature(r"\+(\d+)/", label)

            # F: number of morae in the current accent phrase.
            f1 = _numeric_feature(r"/F:(\d+)_", label)

            a2_next = _numeric_feature(r"\+(\d+)\+", labels[label_idx + 1])

            if (a3 == 1) and (a2_next == 1) and (phone in _MORA_FINAL_PHONES):
                # Last mora of this accent phrase, first mora of the next.
                phones.append(ACCENT_PHRASE_BOUNDARY)
            elif (a1 == 0) and (a2_next == (a2 + 1)) and (a2 != f1):
                # Accent nucleus, and the phrase continues: pitch falls after.
                phones.append(ACCENT_FALL)
            elif (a2 == 1) and (a2_next == 2):
                # Mora 1 -> 2 of an accent phrase: pitch rises.
                phones.append(ACCENT_RISE)

        return phones


def _numeric_feature(pattern: str, label: str) -> int:
    """Extract an integer field from a full-context label."""
    match = re.search(pattern, label)
    if match is None:
        return _NO_FEATURE

    try:
        return int(match.group(1))
    except ValueError:
        # Unset fields are written "xx"
        return _NO_FEATURE


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, keeping the final punctuation."""
    sentences: List[str] = []
    start = 0

    for match in _SENTENCE_END_PATTERN.finditer(text):
        if _is_decimal_point(text, match):
            continue

        sentence = text[start : match.end()].strip()
        if sentence:
            sentences.append(sentence)

        start = match.end()

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)

    return sentences


def _is_decimal_point(text: str, match: "re.Match[str]") -> bool:
    """True for the '.' in "1.5", which is not a sentence boundary."""
    if match.group(0) != ".":
        # Anything longer includes 。/！/？ or trailing space: a real boundary.
        return False

    before = text[match.start() - 1] if match.start() > 0 else ""
    after = text[match.end()] if match.end() < len(text) else ""

    return before.isdigit() and after.isdigit()


def phonemize(
    text: str,
    drop_devoiced_vowels: bool = True,
    use_marine: bool = False,
) -> List[List[str]]:
    """Phonemize Japanese text without holding onto a phonemizer instance."""
    return JapanesePhonemizer(
        drop_devoiced_vowels=drop_devoiced_vowels, use_marine=use_marine
    ).phonemize(text)


def missing_phonemes(
    id_map: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return any phoneme this module can emit that is not in the id map.

    Useful as a sanity check before training: the output should be empty for
    :data:`piper.phoneme_ids.DEFAULT_PHONEME_ID_MAP`.
    """
    if id_map is None:
        from .phoneme_ids import DEFAULT_PHONEME_ID_MAP

        id_map = list(DEFAULT_PHONEME_ID_MAP)

    known = set(id_map)
    emitted = set(PROSODY_SYMBOLS)
    for ipa in OPENJTALK_TO_IPA.values():
        emitted.update(ipa)

    return sorted(emitted - known)
