def initialize(data_dir: str) -> None: ...
"""Initialize espeak-ng."""

def set_voice(voice: str) -> None: ...
"""Set the espeak-ng voice by name."""

def get_phonemes(text: str) -> list[tuple[str, str, bool]]: ...
"""
Convert input text to a list of (phonemes, terminator, end_of_sentence) tuples.

Returns:
    A list where each item is:
        phonemes: str - IPA phonemes for a clause
        terminator: str - punctuation mark indicating clause type (".", "?", "!", ",", ":", ";")
        end_of_sentence: bool - True if the clause ends a sentence
"""
