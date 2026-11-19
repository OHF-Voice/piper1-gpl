"""Tests for the phonemizer dispatch in ``piper.train.infer_torch``.

The regression these guard against: the dispatch over ``config.phoneme_type``
ended in ``else: EspeakPhonemizer``, so a phoneme type without its own branch
(Hebrew) was inferred from raw espeak-ng output with no error (#299).
"""

import io
import json
import sys
import types
from pathlib import Path

import pytest

from piper.config import PhonemeType

infer_torch = pytest.importorskip("piper.train.infer_torch")

_TEST_DIR = Path(__file__).parent

# Module and class of the phonemizer each non-espeak phoneme type must use
_PHONEMIZERS = {
    PhonemeType.PINYIN: ("piper.phonemize_chinese", "ChinesePhonemizer"),
    PhonemeType.HEBREW: ("piper.phonemize_hebrew", "HebrewPhonemizer"),
    PhonemeType.JAPANESE: ("piper.phonemize_japanese", "JapanesePhonemizer"),
    PhonemeType.THAI: ("piper.phonemize_thai", "ThaiPhonemizer"),
    PhonemeType.LITHUANIAN: ("piper.phonemize_lithuanian", "LithuanianPhonemizer"),
}


class _StubModel:
    def __init__(self) -> None:
        dec = types.SimpleNamespace(remove_weight_norm=lambda: None)
        self.model_g = types.SimpleNamespace(dec=dec)

    def eval(self) -> None:
        pass

    def __call__(self, *args, **kwargs):
        return infer_torch.torch.zeros(1, 1, 256)


def _run_infer(monkeypatch, tmp_path, phoneme_type: PhonemeType) -> list:
    """Run infer_torch.main() on one utterance; return the phonemizers used."""
    used = []

    def stub_phonemizer(name: str):
        class Stub:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def phonemize(self, *args, **kwargs):
                used.append(name)
                return []  # no phonemes: the utterance is skipped before synthesis

        return Stub

    for module_name, class_name in _PHONEMIZERS.values():
        module = types.ModuleType(module_name)
        setattr(module, class_name, stub_phonemizer(class_name))
        setattr(module, "phonemes_to_ids", lambda phonemes, id_map: [])
        monkeypatch.setitem(sys.modules, module_name, module)

    monkeypatch.setattr(
        infer_torch, "EspeakPhonemizer", stub_phonemizer("EspeakPhonemizer")
    )
    monkeypatch.setattr(
        infer_torch.VitsModel,
        "load_from_checkpoint",
        lambda *args, **kwargs: _StubModel(),
    )

    config = json.loads((_TEST_DIR / "test_voice.onnx.json").read_text("utf-8"))
    config["phoneme_type"] = phoneme_type.value
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), "utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "infer_torch",
            "--checkpoint",
            "unused.ckpt",
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"text": "x"}) + "\n"))
    infer_torch.main()

    return used


@pytest.mark.parametrize("phoneme_type", list(_PHONEMIZERS))
def test_phoneme_type_uses_its_own_phonemizer(monkeypatch, tmp_path, phoneme_type):
    used = _run_infer(monkeypatch, tmp_path, phoneme_type)
    assert used == [_PHONEMIZERS[phoneme_type][1]]


def test_espeak_uses_espeak(monkeypatch, tmp_path):
    used = _run_infer(monkeypatch, tmp_path, PhonemeType.ESPEAK)
    assert used == ["EspeakPhonemizer"]


def test_text_uses_no_phonemizer(monkeypatch, tmp_path):
    assert not _run_infer(monkeypatch, tmp_path, PhonemeType.TEXT)


def test_every_phoneme_type_is_covered():
    # A new PhonemeType fails here until it has a branch and a case above
    assert set(PhonemeType) == {PhonemeType.ESPEAK, PhonemeType.TEXT, *_PHONEMIZERS}
