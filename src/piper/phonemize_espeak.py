"""Phonemization with espeak-ng."""

import re
import unicodedata
from pathlib import Path
from typing import Union

_DIR = Path(__file__).parent
ESPEAK_DATA_DIR = "/data/data/com.termux/files/usr/share/espeak-ng-data"


class EspeakPhonemizer:
    """Phonemizer that uses espeak-ng."""

    def __init__(self, espeak_data_dir: Union[str, Path] = ESPEAK_DATA_DIR) -> None:
        """Initialize phonemizer."""
        from . import espeakbridge  # avoid circular import

        espeakbridge.initialize(str(espeak_data_dir))

    def phonemize(self, voice: str, text: str) -> list[list[str]]:
        """Text to phonemes grouped by sentence."""
        from . import espeakbridge  # avoid circular import

        espeakbridge.set_voice(voice)

        all_phonemes: list[list[str]] = []
        sentence_phonemes: list[str] = []

        clause_phonemes = espeakbridge.get_phonemes(text)
        for phonemes_str, terminator_str, end_of_sentence in clause_phonemes:
            # Filter out (lang) switch (flags).
            # These surround words from languages other than the current voice.
            phonemes_str = re.sub(r"\([^)]+\)", "", phonemes_str)

            # Keep punctuation even though it's not technically a phoneme
            phonemes_str += terminator_str
            if terminator_str in (",", ":", ";"):
                # Not a sentence boundary
                phonemes_str += " "

            # Decompose phonemes into UTF-8 codepoints.
            # This separates accent characters into separate "phonemes".
            sentence_phonemes.extend(list(unicodedata.normalize("NFD", phonemes_str)))

            if end_of_sentence:
                all_phonemes.append(sentence_phonemes)
                sentence_phonemes = []

        if sentence_phonemes:
            all_phonemes.append(sentence_phonemes)

        return all_phonemes
