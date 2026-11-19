"""Hebrew phonemization: Nakdimon (niqqud) + rule-based Hebrew->IPA G2P.

Hebrew is written without vowel points, and espeak-ng's Hebrew voice is not
robust to fully-pointed text (it falls back to spelling out letter names on many
common words). Instead we restore niqqud with Nakdimon and convert to IPA with a
rule-based G2P. The output uses Piper's default IPA phoneme id map, so Hebrew
voices stay compatible with the IPA-based (espeak) warmstart.
"""

import re
from pathlib import Path
from typing import List, Union

from .hebrew import DEFAULT_MODEL_PATH, NakdimonDiacritizer
from .hebrew.hebrew_ipa import hebrew_to_ipa

# Any Hebrew point -> the text is already diacritized (e.g. training transcripts).
_NIQQUD_PATTERN = re.compile("[ְ-ׇּֿׁׂ]")


class HebrewPhonemizer:
    """Diacritize (if needed) and convert Hebrew text to IPA phonemes."""

    def __init__(self, model_path: Union[str, Path] = DEFAULT_MODEL_PATH) -> None:
        self.diacritizer = NakdimonDiacritizer(model_path)

    def phonemize(self, text: str) -> List[List[str]]:
        """Return IPA phonemes grouped by sentence (one sentence here)."""
        if not _NIQQUD_PATTERN.search(text):
            # Undotted input (e.g. at inference): restore niqqud first. Already
            # dotted input (e.g. training transcripts) is left as-is.
            text = self.diacritizer(text)

        ipa = hebrew_to_ipa(text)
        if not ipa:
            return []

        # IPA symbols are single codepoints in the default map (consonants,
        # vowels, and the stress mark), matching how espeak phonemes are keyed.
        return [list(ipa)]
