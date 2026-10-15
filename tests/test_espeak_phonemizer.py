import subprocess
import sys
from pathlib import Path

from piper.phonemize_espeak import EspeakPhonemizer

from . import EN_US_VOWEL_CLUSTERS

_INITIALIZE_SCRIPT = """
import sys
from piper.phonemize_espeak import EspeakPhonemizer
EspeakPhonemizer(sys.argv[1])
"""


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


def test_long_espeak_data_dir(tmp_path: Path) -> None:
    """Data dir is used as given, even when its path is long."""
    # espeak-ng sizes its data path buffer at 160 bytes off Linux and silently
    # falls back to the build-time default when the path does not fit.
    data_dir = tmp_path / ("d" * 200)
    data_dir.mkdir()

    # The directory is empty, so espeak-ng must fail on this exact path.
    # It exits the process on failure, hence the subprocess.
    result = subprocess.run(
        [sys.executable, "-c", _INITIALIZE_SCRIPT, str(data_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert str(data_dir) in result.stderr
