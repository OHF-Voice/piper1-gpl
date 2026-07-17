"""Hebrew diacritization (niqqud) with Nakdimon.

Hebrew is normally written without niqqud (vowel points), but espeak-ng needs the
points to produce correct phonemes. This module restores them with the Nakdimon
model, mirroring the Arabic ``libtashkeel`` path in :mod:`piper.tashkeel`.

Inference-only port of Nakdimon (https://github.com/elazarg/nakdimon, MIT).
The character tables and merge logic are vendored from ``nakdimon/hebrew.py`` and
``nakdimon/dataset.py`` so the package is self-contained (no upstream/TensorFlow
dependency at runtime). See ``LICENSE`` and ``SOURCE`` in this directory.
"""

import re
from pathlib import Path
from typing import List, Optional, Union

import numpy as np
from onnxruntime import InferenceSession

HEBREW_DIR = Path(__file__).parent
DEFAULT_MODEL_PATH = HEBREW_DIR / "nakdimon.onnx"

# --- vendored from nakdimon/hebrew.py ---------------------------------------

# "rafe": a letter that could have taken a diacritic but did not. Stripped from
# the final output; kept only so the tables line up with the model's classes.
RAFE = "ֿ"

HEBREW_LETTERS = [chr(c) for c in range(0x05D0, 0x05EA + 1)]

# 16 niqqud classes once the mask token is prepended (matches ONNX head "N").
NIQQUD = [RAFE] + [chr(c) for c in range(0x05B0, 0x05BC + 1)] + ["ַ"]

SHIN_YEMANIT = "ׁ"
SHIN_SMALIT = "ׂ"
NIQQUD_SIN = [RAFE, SHIN_YEMANIT, SHIN_SMALIT]  # -> ONNX head "S" (4 w/ mask)

DAGESH_LETTER = "ּ"
DAGESH = [RAFE, DAGESH_LETTER]  # -> ONNX head "D" (3 w/ mask)

VALID_LETTERS = [
    " ",
    "!",
    '"',
    "'",
    "(",
    ")",
    ",",
    "-",
    ".",
    ":",
    ";",
    "?",
] + HEBREW_LETTERS
SPECIAL_TOKENS = ["H", "O", "5"]

ENDINGS_TO_REGULAR = dict(zip("ךםןףץ", "כמנפצ"))

_NIQQUD_PATTERN = re.compile("[ְ-ׇּֿׁׂ]")


def remove_niqqud(text: str) -> str:
    """Strip any existing points so the model sees bare consonants."""
    return _NIQQUD_PATTERN.sub("", text)


def normalize(c: str) -> str:
    """Map a character to the model's input alphabet."""
    if c in VALID_LETTERS:
        return c
    if c in ENDINGS_TO_REGULAR:
        return ENDINGS_TO_REGULAR[c]
    if c in ("\n", "\t"):
        return " "
    if c in ("־", "‒", "–", "—", "―", "−"):
        return "-"
    if c == "[":
        return "("
    if c == "]":
        return ")"
    if c in ("´", "‘", "’"):
        return "'"
    if c in ("“", "”", "״"):
        return '"'
    if c.isdigit():
        return "5"
    if c == "…":
        return ","
    if c in ("ײ", "װ", "ױ"):
        return "H"
    return "O"


def can_dagesh(letter: str) -> bool:
    return letter in ("בגדהוזטיכלמנספצקשת" + "ךף")


def can_sin(letter: str) -> bool:
    return letter == "ש"


def can_niqqud(letter: str) -> bool:
    return letter in ("אבגדהוזחטיכלמנסעפצקרשת" + "ךן")


# --- vendored from nakdimon/dataset.py (CharacterTable) ----------------------

# Each table prepends the empty mask token at index 0, so head class index -> char
# is a direct lookup. This is what makes the ONNX heads N=16, D=3, S=4.
_LETTER_CHARS = [""] + SPECIAL_TOKENS + VALID_LETTERS
_NIQQUD_CHARS = [""] + NIQQUD
_DAGESH_CHARS = [""] + DAGESH
_SIN_CHARS = [""] + NIQQUD_SIN

_CHAR_TO_ID = {c: i for i, c in enumerate(_LETTER_CHARS)}


class NakdimonDiacritizer:
    """Add niqqud to Hebrew text with Nakdimon."""

    def __init__(self, model_path: Union[str, Path] = DEFAULT_MODEL_PATH) -> None:
        """Initialize diacritizer."""
        self.session = InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._input_name = self.session.get_inputs()[0].name

    def __call__(self, text: str, taskeen_threshold: Optional[float] = None) -> str:
        """Add niqqud (``taskeen_threshold`` accepted for API parity, unused)."""
        return self.diacritize(text)

    def diacritize(self, text: str) -> str:
        """Return ``text`` with niqqud restored."""
        text = remove_niqqud(text)
        letters = list(text)
        if not letters:
            return text

        # This model takes the character ids as float (embedding lookup is baked
        # into the graph), unlike upstream Nakdimon which takes int32.
        input_ids = np.array(
            [[_CHAR_TO_ID[normalize(c)] for c in letters]], dtype=np.float32
        )
        n_out, d_out, s_out = self.session.run(None, {self._input_name: input_ids})

        niqqud = np.argmax(n_out[0], axis=-1)
        dagesh = np.argmax(d_out[0], axis=-1)
        sin = np.argmax(s_out[0], axis=-1)

        out: List[str] = []
        for letter, n_id, d_id, s_id in zip(letters, niqqud, dagesh, sin):
            out.append(letter)
            # Order matches Nakdimon's merge: dagesh, sin, niqqud.
            if can_dagesh(letter):
                out.append(_DAGESH_CHARS[d_id])
            if can_sin(letter):
                out.append(_SIN_CHARS[s_id])
            if can_niqqud(letter):
                out.append(_NIQQUD_CHARS[n_id])

        # Marks are emitted in Nakdimon's order (dagesh, sin/shin dot, vowel),
        # which is the traditional Hebrew storage order espeak-ng expects. Do NOT
        # NFC-normalize: that reorders the vowel before the shin dot and makes
        # espeak-ng fall back to spelling out letter names.
        return "".join(out).replace(RAFE, "")
