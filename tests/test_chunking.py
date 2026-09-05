"""Tests for text chunking."""

import pytest

from piper.chunking import (
    PROFILES,
    ChunkingConfig,
    chunk_text,
    iter_chunks,
    normalize_text,
)


def test_disabled_chunking() -> None:
    """Text is passed through unchanged (but normalized) when disabled."""
    chunks = list(chunk_text("Hello\nworld.  Again.", PROFILES["off"]))
    assert chunks == ["Hello world. Again."]


def test_empty_text() -> None:
    assert not list(chunk_text("   \n\t "))


def test_normalize_text() -> None:
    assert normalize_text(" a \n b\tc  ") == "a b c"


def test_first_chunk_is_shorter() -> None:
    """Time-to-first-audio is what matters: the first chunk is smaller."""
    config = ChunkingConfig(max_words=5, first_max_words=2, min_words=1)
    chunks = list(chunk_text("one two three four five six seven eight", config))
    assert chunks[0] == "one two"
    assert all(len(chunk.split()) <= 5 for chunk in chunks)


def test_break_on_sentence() -> None:
    """A sentence boundary always ends a chunk."""
    chunks = list(chunk_text("Alpha beta. Gamma delta epsilon zeta.", ChunkingConfig()))
    assert chunks[0] == "Alpha beta."


def test_break_on_clause() -> None:
    config = ChunkingConfig(max_words=10, first_max_words=0, min_words=2)
    chunks = list(chunk_text("Hello there, my dear friend, how are you?", config))
    assert chunks[0] == "Hello there,"
    assert chunks[1] == "my dear friend,"


def test_clause_break_respects_min_words() -> None:
    config = ChunkingConfig(max_words=10, first_max_words=0, min_words=3)
    chunks = list(chunk_text("Yes, indeed my friend, this is fine.", config))
    assert chunks[0] == "Yes, indeed my friend,"


def test_abbreviations_are_not_sentence_ends() -> None:
    config = ChunkingConfig(max_words=10, first_max_words=0, min_words=1)
    chunks = list(chunk_text("Mr. Smith and Dr. Jones arrived.", config))
    assert chunks == ["Mr. Smith and Dr. Jones arrived."]


def test_initials_are_not_sentence_ends() -> None:
    config = ChunkingConfig(max_words=10, first_max_words=0, min_words=1)
    chunks = list(chunk_text("Written by J. R. Tolkien here.", config))
    assert chunks == ["Written by J. R. Tolkien here."]


def test_short_tail_is_merged() -> None:
    """A dangling one-word chunk is merged into the previous one."""
    config = ChunkingConfig(max_words=3, first_max_words=3, min_words=2)
    chunks = list(chunk_text("one two three four", config))
    assert chunks == ["one two three four"]

    config.merge_short_tail = False
    assert list(chunk_text("one two three four", config)) == ["one two three", "four"]


def test_max_chars_splits_long_words() -> None:
    """Inference time must stay bounded even without whitespace."""
    text = "x" * 100
    chunks = list(chunk_text(text, ChunkingConfig(max_chars=30)))
    assert all(len(chunk) <= 30 for chunk in chunks)
    assert "".join(chunks) == text


def test_chunk_offsets() -> None:
    """Offsets allow the caller to map audio back to the source text."""
    text = "Alpha beta. Gamma delta."
    chunks = list(iter_chunks(text, ChunkingConfig()))
    for chunk in chunks:
        assert text[chunk.start : chunk.end] == chunk.text

    assert chunks[-1].is_last
    assert not chunks[0].is_last
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_profiles_are_ordered_by_latency() -> None:
    assert PROFILES["instant"].first_limit <= PROFILES["responsive"].first_limit
    assert PROFILES["responsive"].first_limit <= PROFILES["balanced"].first_limit
    assert not PROFILES["off"].enabled
    assert not PROFILES["smooth"].break_on_clause


def test_from_mapping_with_prefix_and_profile() -> None:
    config = ChunkingConfig.from_mapping(
        {
            "PIPER_CHUNK_PROFILE": "instant",
            "PIPER_CHUNK_MAX_WORDS": "7",
            "PIPER_CHUNK_MERGE_SHORT_TAIL": "false",
            "UNRELATED": "x",
        },
        prefix="piper_chunk_",
    )
    assert config.max_words == 7
    assert config.first_max_words == PROFILES["instant"].first_max_words
    assert config.merge_short_tail is False


def test_from_mapping_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError):
        ChunkingConfig.from_mapping({"profile": "nope"})


def test_from_mapping_abbreviations_from_string() -> None:
    config = ChunkingConfig.from_mapping({"abbreviations": "abc,Def"})
    assert config.abbreviations == {"abc", "def"}
