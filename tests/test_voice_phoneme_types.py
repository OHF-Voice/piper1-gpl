"""Tests for the phonemizer dispatch in ``PiperVoice.phonemize``.

The regression these guard against: the dispatch over ``config.phoneme_type``
ended in ``else: espeak``, so a phoneme type without its own branch was
phonemized with raw espeak-ng output and no error (#299). The training-side
dispatch has the same guard (tests/test_train_infer_torch.py); this is the
inference-side equivalent.
"""

import pytest

from piper.config import PhonemeType, PiperConfig
from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP
from piper.voice import PiperVoice

# Module and class of the phonemizer each non-espeak phoneme type must use
_PHONEMIZERS = {
    PhonemeType.PINYIN: ("piper.phonemize_chinese", "ChinesePhonemizer"),
    PhonemeType.HEBREW: ("piper.phonemize_hebrew", "HebrewPhonemizer"),
    PhonemeType.JAPANESE: ("piper.phonemize_japanese", "JapanesePhonemizer"),
    PhonemeType.THAI: ("piper.phonemize_thai", "ThaiPhonemizer"),
    PhonemeType.LITHUANIAN: ("piper.phonemize_lithuanian", "LithuanianPhonemizer"),
}


def _voice(phoneme_type: PhonemeType) -> PiperVoice:
    """A voice with no model, only far enough to phonemize."""
    config = PiperConfig(
        num_symbols=256,
        num_speakers=1,
        sample_rate=22050,
        espeak_voice="en-us",
        phoneme_id_map=DEFAULT_PHONEME_ID_MAP,
        phoneme_type=phoneme_type,
    )
    return PiperVoice(session=None, config=config)  # type: ignore[arg-type]


def _stub_phonemizer(monkeypatch, module_name: str, class_name: str) -> list:
    """Replace a phonemizer class with a stub; return the names it was used as."""
    used = []

    class Stub:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def phonemize(self, text, *args, **kwargs):
            used.append(class_name)
            return [["x"]]

    monkeypatch.setattr(f"{module_name}.{class_name}", Stub)
    return used


@pytest.mark.parametrize("phoneme_type", list(_PHONEMIZERS))
def test_phoneme_type_uses_its_own_phonemizer(monkeypatch, phoneme_type):
    module_name, class_name = _PHONEMIZERS[phoneme_type]
    used = _stub_phonemizer(monkeypatch, module_name, class_name)
    assert _voice(phoneme_type).phonemize("test") == [["x"]]
    assert used == [class_name]


def test_espeak_uses_espeak():
    phonemes = _voice(PhonemeType.ESPEAK).phonemize("Test.")
    assert phonemes and all(phonemes)


def test_text_uses_no_phonemizer():
    assert _voice(PhonemeType.TEXT).phonemize("ab") == [["a", "b"]]


def test_every_phoneme_type_is_covered():
    # A new PhonemeType fails here until it has a branch and a case above
    assert set(PhonemeType) == {PhonemeType.ESPEAK, PhonemeType.TEXT, *_PHONEMIZERS}
