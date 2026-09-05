"""Configurable text chunking for low-latency streaming synthesis.

Screen readers hand over arbitrarily large blocks of text. Synthesis granularity
in Piper is one sentence, so a long sentence means a long wait before the first
sample is heard. Splitting text into small pieces *before* synthesis is what
makes time-to-first-audio short and predictable.

Splitting is always a trade-off: smaller pieces start faster but prosody
suffers and boundary artifacts become audible. Nothing here is hardcoded --
every knob is exposed through :class:`ChunkingConfig`, which can be built from
CLI arguments, environment variables, a speech-dispatcher module config file or
a JSON request body, and can be tuned per user.

Example::

    >>> config = ChunkingConfig(max_words=4, first_max_words=2)
    >>> list(chunk_text("Hello there, world. This is a test.", config))
    ['Hello there,', 'world.', 'This is a test.']
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, replace
from typing import Any, Iterable, Iterator, List, Mapping, Optional, Set, Tuple

__all__ = [
    "ChunkingConfig",
    "PROFILES",
    "chunk_text",
    "iter_chunks",
    "TextChunk",
]

# Boundary strengths
_WORD = 1
_CLAUSE = 2
_SENTENCE = 3

_WHITESPACE_PATTERN = re.compile(r"\s+")

# Characters that are stripped when deciding what a "word" is
_TRAILING_PUNCTUATION = "\"'’”)]}»"

DEFAULT_SENTENCE_PUNCTUATION = ".!?…。！？"
DEFAULT_CLAUSE_PUNCTUATION = ",;:—–)"

# Words that end with a period without ending a sentence.
DEFAULT_ABBREVIATIONS: Set[str] = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "st",
    "vs",
    "etc",
    "eg",
    "e.g",
    "ie",
    "i.e",
    "no",
    "fig",
    "al",
    "inc",
    "ltd",
    "jr",
    "sr",
    "approx",
    "min",
    "max",
    "vol",
    "cf",
}


@dataclass(frozen=True)
class TextChunk:
    """A piece of text to synthesize, with its position in the source text."""

    text: str
    """Text of the chunk (whitespace normalized)."""

    start: int
    """Offset of the chunk in the (normalized) source text."""

    end: int
    """End offset (exclusive) of the chunk in the (normalized) source text."""

    index: int
    """Zero-based index of the chunk."""

    is_last: bool = False
    """True if this is the final chunk of the text."""


@dataclass
class ChunkingConfig:
    """How text is split before being synthesized.

    All defaults aim at screen-reader responsiveness: a very short first chunk
    so speech starts almost immediately, then slightly larger chunks so that
    prosody stays acceptable.
    """

    enabled: bool = True
    """False disables splitting entirely (one chunk per input text)."""

    max_words: int = 5
    """Maximum number of words per chunk (0 = unlimited)."""

    first_max_words: int = 3
    """Maximum number of words in the *first* chunk (0 = same as max_words).

    The first chunk determines time-to-first-audio, so it usually pays to make
    it smaller than the others.
    """

    min_words: int = 2
    """Do not break at a sentence/clause boundary before this many words.

    Prevents pathological one-word chunks such as "Yes." followed by "OK."
    being synthesized separately.
    """

    max_chars: int = 0
    """Hard cap on chunk length in characters (0 = unlimited).

    A single "word" can be arbitrarily long (URLs, base64, code). This is the
    safety net that keeps inference time bounded.
    """

    merge_short_tail: bool = True
    """Merge a trailing chunk shorter than ``min_words`` into the previous one."""

    break_on_sentence: bool = True
    """Break at sentence punctuation (once ``min_words`` is reached)."""

    break_on_clause: bool = True
    """Break at clause punctuation such as commas (once ``min_words`` is reached)."""

    sentence_punctuation: str = DEFAULT_SENTENCE_PUNCTUATION
    """Characters that end a sentence."""

    clause_punctuation: str = DEFAULT_CLAUSE_PUNCTUATION
    """Characters that end a clause."""

    abbreviations: Set[str] = field(default_factory=lambda: set(DEFAULT_ABBREVIATIONS))
    """Lowercase words that end with '.' without ending a sentence."""

    strip_urls: bool = False
    """Replace URLs with their host name (they are painful to listen to)."""

    def __post_init__(self) -> None:
        # Be forgiving with values coming from config files/environment
        self.max_words = max(0, int(self.max_words))
        self.first_max_words = max(0, int(self.first_max_words))
        self.min_words = max(1, int(self.min_words))
        self.max_chars = max(0, int(self.max_chars))

        # Be tolerant of a comma-separated string (config files, environment)
        self.abbreviations = _as_word_set(self.abbreviations)

    # -------------------------------------------------------------------------

    @property
    def first_limit(self) -> int:
        """Word limit for the first chunk."""
        if self.first_max_words:
            if self.max_words:
                return min(self.first_max_words, self.max_words)

            return self.first_max_words

        return self.max_words

    def replace(self, **changes: Any) -> "ChunkingConfig":
        """Return a copy with the given fields changed (ignores None values)."""
        changes = {key: value for key, value in changes.items() if value is not None}
        return replace(self, **changes)

    # -------------------------------------------------------------------------

    @staticmethod
    def from_mapping(
        values: Mapping[str, Any],
        prefix: str = "",
        base: Optional["ChunkingConfig"] = None,
    ) -> "ChunkingConfig":
        """Build a config from a mapping (JSON body, env vars, config file).

        Keys are matched case-insensitively, with ``-``/``_`` treated the same,
        and may be prefixed (e.g. ``PIPER_CHUNK_MAX_WORDS`` with
        ``prefix="piper_chunk_"``). Unknown keys are ignored so the same
        mapping can carry unrelated settings.

        A ``profile`` key selects one of :data:`PROFILES` as the base.
        """
        normalized = {
            _normalize_key(key): value
            for key, value in values.items()
            if _normalize_key(key).startswith(_normalize_key(prefix))
        }
        prefix_len = len(_normalize_key(prefix))
        normalized = {key[prefix_len:]: value for key, value in normalized.items()}

        config = base
        profile = normalized.get("profile")
        if profile:
            profile_config = PROFILES.get(str(profile).strip().lower())
            if profile_config is None:
                raise ValueError(
                    f"Unknown chunking profile: {profile} "
                    f"(expected one of {sorted(PROFILES)})"
                )
            config = profile_config

        config = replace(config) if config is not None else ChunkingConfig()

        for config_field in fields(ChunkingConfig):
            if config_field.name not in normalized:
                continue

            raw_value = normalized[config_field.name]
            setattr(
                config,
                config_field.name,
                _coerce(
                    config_field.name, raw_value, getattr(config, config_field.name)
                ),
            )

        config.__post_init__()
        return config


def _as_word_set(value: Any) -> Set[str]:
    """Convert a comma-separated string or an iterable into a set of words."""
    if isinstance(value, str):
        return {word.strip().lower() for word in value.split(",") if word.strip()}

    return {str(word).strip().lower() for word in value}


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _coerce(name: str, value: Any, current: Any) -> Any:
    """Convert a string value to the type of the current field value."""
    if isinstance(current, bool):
        if isinstance(value, str):
            value = value.strip().lower()
            if value in ("1", "true", "yes", "on"):
                return True
            if value in ("0", "false", "no", "off"):
                return False
            raise ValueError(f"Invalid boolean for {name}: {value}")

        return bool(value)

    if isinstance(current, int):
        return int(value)

    if isinstance(current, set):
        return _as_word_set(value)

    return value


#: Named presets. Users (and bug reports) can refer to these by name.
PROFILES: "dict[str, ChunkingConfig]" = {
    # Absolute minimum latency: start speaking after two words.
    "instant": ChunkingConfig(max_words=3, first_max_words=2, min_words=1),
    # Recommended default for screen reading.
    "responsive": ChunkingConfig(max_words=5, first_max_words=3, min_words=2),
    # Compromise: quick start, longer pieces afterwards.
    "balanced": ChunkingConfig(max_words=10, first_max_words=4, min_words=3),
    # Prosody first: only break at sentences (still streams per sentence).
    "smooth": ChunkingConfig(
        max_words=0, first_max_words=0, min_words=2, break_on_clause=False
    ),
    # No client-side splitting at all.
    "off": ChunkingConfig(enabled=False),
}

_URL_PATTERN = re.compile(r"\b(?:https?|ftp)://(\S+)")


def normalize_text(text: str, config: Optional[ChunkingConfig] = None) -> str:
    """Collapse whitespace (including newlines) into single spaces."""
    if (config is not None) and config.strip_urls:
        text = _URL_PATTERN.sub(lambda m: m.group(1).split("/")[0], text)

    return _WHITESPACE_PATTERN.sub(" ", text).strip()


def _boundary_strength(token: str, config: ChunkingConfig) -> int:
    """Return the boundary strength after ``token``."""
    stripped = token.rstrip(_TRAILING_PUNCTUATION)
    if not stripped:
        return _WORD

    last_char = stripped[-1]
    if last_char in config.sentence_punctuation:
        if last_char == ".":
            word = stripped[:-1].lower()
            # "Mr." / "e.g." / initials ("J.") do not end a sentence
            if word in config.abbreviations:
                return _WORD

            if len(word) == 1 and word.isalpha():
                return _WORD

            if word.isdigit():
                # "1. First item" -- list numbering, weak boundary
                return _CLAUSE

        return _SENTENCE

    if last_char in config.clause_punctuation:
        return _CLAUSE

    return _WORD


def iter_chunks(
    text: str, config: Optional[ChunkingConfig] = None
) -> Iterator[TextChunk]:
    """Split text into :class:`TextChunk` objects.

    Chunks are yielded lazily so that synthesis of the first chunk can start
    while the rest of the text is still being split.
    """
    if config is None:
        config = ChunkingConfig()

    text = normalize_text(text, config)
    if not text:
        return

    if not config.enabled:
        yield TextChunk(text=text, start=0, end=len(text), index=0, is_last=True)
        return

    pending: List[TextChunk] = []
    for chunk in _split(text, config):
        # Keep one chunk in hand so a short tail can be merged into it
        pending.append(chunk)
        if len(pending) > 1:
            yield pending.pop(0)

    if not pending:
        return

    last = pending[0]
    yield TextChunk(
        text=last.text, start=last.start, end=last.end, index=last.index, is_last=True
    )


def _split(text: str, config: ChunkingConfig) -> Iterator[TextChunk]:
    """Greedy split at the strongest boundary allowed by the limits."""
    index = 0
    start: Optional[int] = None
    end = 0
    num_words = 0

    def limit() -> int:
        return config.first_limit if index == 0 else config.max_words

    prev_chunk: Optional[TextChunk] = None

    for token, token_start, token_end in _iter_tokens(text, config.max_chars):
        if start is None:
            start = token_start

        # Hard character cap: emit what we have before adding this token
        if config.max_chars and num_words and ((token_end - start) > config.max_chars):
            chunk = TextChunk(text=text[start:end], start=start, end=end, index=index)
            prev_chunk, emit = _merge_tail(prev_chunk, chunk, config)
            if emit is not None:
                yield emit

            index += 1
            start = token_start
            num_words = 0

        end = token_end
        num_words += 1

        strength = _boundary_strength(token, config)
        should_break = False
        if (strength == _SENTENCE) and config.break_on_sentence:
            # Piper synthesizes one sentence at a time anyway: never merge
            # across a sentence boundary, whatever min_words says.
            should_break = True
        elif (
            (strength == _CLAUSE)
            and config.break_on_clause
            and (num_words >= config.min_words)
        ):
            should_break = True

        if (not should_break) and limit() and (num_words >= limit()):
            should_break = True

        if config.max_chars and ((end - start) >= config.max_chars):
            should_break = True

        if should_break:
            chunk = TextChunk(text=text[start:end], start=start, end=end, index=index)
            prev_chunk, emit = _merge_tail(prev_chunk, chunk, config)
            if emit is not None:
                yield emit

            index += 1
            start = None
            num_words = 0

    if start is not None:
        chunk = TextChunk(text=text[start:end], start=start, end=end, index=index)
        prev_chunk, emit = _merge_tail(prev_chunk, chunk, config)
        if emit is not None:
            yield emit

    if prev_chunk is not None:
        yield prev_chunk


def _merge_tail(
    prev_chunk: Optional[TextChunk], chunk: TextChunk, config: ChunkingConfig
) -> Tuple[Optional[TextChunk], Optional[TextChunk]]:
    """Hold back one chunk so a too-short chunk can be merged with it.

    Returns (chunk to hold, chunk to emit now).
    """
    if prev_chunk is None:
        return chunk, None

    if not config.merge_short_tail:
        return chunk, prev_chunk

    too_short = _count_words(chunk.text) < config.min_words
    if too_short:
        merged_text = f"{prev_chunk.text} {chunk.text}"
        if (not config.max_chars) or (len(merged_text) <= config.max_chars):
            return (
                TextChunk(
                    text=merged_text,
                    start=prev_chunk.start,
                    end=chunk.end,
                    index=prev_chunk.index,
                ),
                None,
            )

    return chunk, prev_chunk


def _count_words(text: str) -> int:
    return len(text.split())


def _iter_tokens(text: str, max_chars: int = 0) -> Iterator[Tuple[str, int, int]]:
    """Yield (token, start, end) for whitespace-separated tokens.

    Tokens longer than ``max_chars`` (URLs, base64 blobs, code) are hard-split
    so that inference time per chunk stays bounded.
    """
    for match in re.finditer(r"\S+", text):
        token, start, end = match.group(0), match.start(), match.end()
        if max_chars and (len(token) > max_chars):
            for offset in range(0, len(token), max_chars):
                piece = token[offset : offset + max_chars]
                yield piece, start + offset, start + offset + len(piece)

            continue

        yield token, start, end


def chunk_text(text: str, config: Optional[ChunkingConfig] = None) -> Iterable[str]:
    """Split text and yield chunk strings (convenience wrapper)."""
    for chunk in iter_chunks(text, config):
        yield chunk.text
