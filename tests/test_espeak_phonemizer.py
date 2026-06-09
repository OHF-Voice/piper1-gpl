from piper.phonemize_espeak import EspeakPhonemizer


def test_phonemize() -> None:
    """Sanity check for phonemizer."""
    phonemizer = EspeakPhonemizer()
    assert phonemizer.phonemize("en-us", "test") == [
        ["t", "ˈ", "ɛ", "s", "t"],
    ]


def test_merge_vowels() -> None:
    """Test merging vowel clusters (dipthongs)."""
    phonemizer = EspeakPhonemizer()

    # my
    assert phonemizer.phonemize("en-us", "my") == [
        ["m", "ˈ", "a", "ɪ"],
    ]
    assert phonemizer.phonemize("en-us", "my", merge_vowels=True) == [
        ["m", "ˈ", "aɪ"],
    ]

    # cow
    assert phonemizer.phonemize("en-us", "cow") == [
        ["k", "ˈ", "a", "ʊ"],
    ]
    assert phonemizer.phonemize("en-us", "cow", merge_vowels=True) == [
        ["k", "ˈ", "aʊ"],
    ]

    # toy
    assert phonemizer.phonemize("en-us", "toy") == [
        ["t", "ˈ", "ɔ", "ɪ"],
    ]
    assert phonemizer.phonemize("en-us", "toy", merge_vowels=True) == [
        ["t", "ˈ", "ɔɪ"],
    ]

    # day
    assert phonemizer.phonemize("en-us", "day") == [
        ["d", "ˈ", "e", "ɪ"],
    ]
    assert phonemizer.phonemize("en-us", "day", merge_vowels=True) == [
        ["d", "ˈ", "eɪ"],
    ]

    # no
    assert phonemizer.phonemize("en-us", "no") == [
        ["n", "ˈ", "o", "ʊ"],
    ]
    assert phonemizer.phonemize("en-us", "no", merge_vowels=True) == [
        ["n", "ˈ", "oʊ"],
    ]
