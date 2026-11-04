"""Hebrew phonemization with renikud (text -> stressed IPA).

Hebrew is written without vowel points, and espeak-ng's Hebrew voice is not
robust to fully-pointed text (it falls back to spelling out letter names on many
common words). renikud predicts each letter's consonant, vowel and the word
stress directly from unvocalized text. The output uses Piper's default IPA
phoneme id map, so Hebrew voices stay compatible with the IPA-based (espeak)
warmstart.
"""

import re
import unicodedata
from pathlib import Path
from typing import List, Union

from .hebrew import DEFAULT_MODEL_PATH, RenikudG2P

# Hebrew points and cantillation; renikud reads unvocalized text, so dotted
# input (e.g. training transcripts) is stripped first.
_NIQQUD_PATTERN = re.compile("[֑-ׇֽֿׁׂׅׄ]")


class HebrewPhonemizer:
    """Convert Hebrew text to IPA phonemes."""

    def __init__(self, model_path: Union[str, Path] = DEFAULT_MODEL_PATH) -> None:
        self.g2p = RenikudG2P(model_path)

    def phonemize(self, text: str) -> List[List[str]]:
        """Return IPA phonemes grouped by sentence (one sentence here)."""
        text = _NIQQUD_PATTERN.sub("", unicodedata.normalize("NFD", text))
        ipa = unicodedata.normalize("NFD", self.g2p(text)).strip()
        if not ipa:
            return []

        # IPA symbols are single codepoints in the default map (consonants,
        # vowels, and the stress mark), matching how espeak phonemes are keyed.
        return [list(ipa)]
