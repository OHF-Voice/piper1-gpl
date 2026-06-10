from piper.phonemize_espeak import EspeakPhonemizer

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
