"""Phonemization with espeak-ng."""

import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

_DIR = Path(__file__).parent
ESPEAK_DATA_DIR = _DIR / "espeak-ng-data"

from collections.abc import Sequence


class EspeakPhonemizer:
    """Phonemizer that uses espeak-ng."""

    def __init__(self, espeak_data_dir: Union[str, Path] = ESPEAK_DATA_DIR) -> None:
        """Initialize phonemizer."""
        from . import espeakbridge  # avoid circular import

        espeakbridge.initialize(str(espeak_data_dir))

    def phonemize(
        self,
        voice: str,
        text: str,
        vowel_clusters: Optional[Set[Tuple[str, ...]]] = None,
    ) -> list[list[str]]:
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
                if vowel_clusters:
                    sentence_phonemes = _merge_known_vowel_clusters(
                        sentence_phonemes, vowel_clusters
                    )

                all_phonemes.append(sentence_phonemes)
                sentence_phonemes = []

        if sentence_phonemes:
            # Text without a final sentence terminator
            if vowel_clusters:
                sentence_phonemes = _merge_known_vowel_clusters(
                    sentence_phonemes, vowel_clusters
                )

            all_phonemes.append(sentence_phonemes)

        return all_phonemes


def _merge_known_vowel_clusters(
    phones: Sequence[str], clusters: Set[Tuple[str, ...]]
) -> List[str]:
    """Merge adjacent recognized vowel clusters."""
    max_len = max(len(k) for k in clusters)
    out: list[str] = []
    i = 0

    while i < len(phones):
        match: Tuple[str, ...] | None = None

        for n in range(min(max_len, len(phones) - i), 1, -1):
            candidate = tuple(phones[i : i + n])
            if candidate in clusters:
                match = candidate
                break

        if match is not None:
            out.append("".join(match))
            i += len(match)
        else:
            out.append(phones[i])
            i += 1

    return out
