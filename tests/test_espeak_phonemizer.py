import os

from piper.phonemize_espeak import ESPEAK_DATA_DIR, EspeakPhonemizer

from . import EN_US_VOWEL_CLUSTERS


def test_phonemize() -> None:
    """Sanity check for phonemizer."""
    phonemizer = EspeakPhonemizer()
    assert phonemizer.phonemize("en-us", "test") == [
        ["t", "ˈ", "ɛ", "s", "t"],
    ]


def test_vowel_clusters() -> None:
    """Test merging vowel clusters (diphthongs)."""
    phonemizer = EspeakPhonemizer()

    # my
    assert phonemizer.phonemize("en-us", "my") == [
        ["m", "ˈ", "a", "ɪ"],
    ]
    assert phonemizer.phonemize("en-us", "my", vowel_clusters=EN_US_VOWEL_CLUSTERS) == [
        ["m", "ˈ", "aɪ"],
    ]

    # cow
    assert phonemizer.phonemize("en-us", "cow") == [
        ["k", "ˈ", "a", "ʊ"],
    ]
    assert phonemizer.phonemize(
        "en-us", "cow", vowel_clusters=EN_US_VOWEL_CLUSTERS
    ) == [
        ["k", "ˈ", "aʊ"],
    ]

    # toy
    assert phonemizer.phonemize("en-us", "toy") == [
        ["t", "ˈ", "ɔ", "ɪ"],
    ]
    assert phonemizer.phonemize(
        "en-us", "toy", vowel_clusters=EN_US_VOWEL_CLUSTERS
    ) == [
        ["t", "ˈ", "ɔɪ"],
    ]

    # day
    assert phonemizer.phonemize("en-us", "day") == [
        ["d", "ˈ", "e", "ɪ"],
    ]
    assert phonemizer.phonemize(
        "en-us", "day", vowel_clusters=EN_US_VOWEL_CLUSTERS
    ) == [
        ["d", "ˈ", "eɪ"],
    ]

    # no
    assert phonemizer.phonemize("en-us", "no") == [
        ["n", "ˈ", "o", "ʊ"],
    ]
    assert phonemizer.phonemize("en-us", "no", vowel_clusters=EN_US_VOWEL_CLUSTERS) == [
        ["n", "ˈ", "oʊ"],
    ]


def test_vowel_clusters_without_terminator() -> None:
    """Clusters are merged even when text has no final sentence terminator."""
    phonemizer = EspeakPhonemizer()

    # "my" with no punctuation still merges the trailing diphthong.
    assert phonemizer.phonemize("en-us", "my", vowel_clusters=EN_US_VOWEL_CLUSTERS) == [
        ["m", "ˈ", "aɪ"],
    ]


def test_phonemizers_share_one_initialization() -> None:
    """Creating another phonemizer must not re-initialize espeak-ng under the
    first. Re-initializing freed the phoneme tables the current voice pointed
    into, so the next phonemize() read freed memory; under valgrind that was
    hundreds of invalid reads, and on CI a segfault."""
    first = EspeakPhonemizer()
    expected = first.phonemize("lt", "Labas, mama.")

    for _ in range(3):
        assert EspeakPhonemizer().phonemize("lt", "Labas, mama.") == expected

    assert first.phonemize("lt", "Labas, mama.") == expected


def test_switching_data_directory() -> None:
    """A different data directory tears espeak-ng down before initializing it
    again, rather than reloading over live state."""
    expected = EspeakPhonemizer().phonemize("en-us", "test")

    # Same directory, spelled differently, so the bridge sees a new one.
    other = EspeakPhonemizer(str(ESPEAK_DATA_DIR) + os.sep)
    assert other.phonemize("en-us", "test") == expected

    assert EspeakPhonemizer().phonemize("en-us", "test") == expected
