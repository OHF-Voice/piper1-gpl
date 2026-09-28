"""Tests for warmstart behavior when resuming training.

The regression these guard against: ``LightningCLI._parse_ckpt_path`` merges a
resumed checkpoint's saved ``hyper_parameters`` back over the parsed config, so
``warmstart_ckpt`` reappears even when it is absent from the command line.
Trainer restores model weights *before* ``on_fit_start`` and the optimizer/loop
state *after* it, so warmstarting on a resume replaces the resumed weights with
the base model while keeping the restored epoch -- discarding all training done
so far with only a log line to show for it.
"""

# Setting _trainer/_warmstart_ckpt is deliberate: they are what this module
# asserts about.
# pylint: disable=protected-access

from typing import Optional

import pytest

lightning_module = pytest.importorskip("piper.train.vits.lightning")

VitsModel = lightning_module.VitsModel


class _StubTrainer:
    def __init__(self, ckpt_path: Optional[str] = None) -> None:
        self.ckpt_path = ckpt_path
        self.max_epochs = 10


def _tiny_model(**kwargs) -> "VitsModel":
    return VitsModel(
        num_symbols=32,
        num_speakers=1,
        inter_channels=16,
        hidden_channels=16,
        filter_channels=32,
        n_layers=2,
        upsample_initial_channel=16,
        mos_metric=None,
        **kwargs,
    )


def _record_warmstarts(model, monkeypatch) -> list:
    called: list = []
    monkeypatch.setattr(
        model, "_warmstart_from_ckpt", lambda path: called.append(("full", path))
    )
    monkeypatch.setattr(
        model,
        "_warmstart_vocoder_from_ckpt",
        lambda path: called.append(("vocoder", path)),
    )
    return called


def test_warmstart_runs_on_a_fresh_fit(monkeypatch) -> None:
    model = _tiny_model(warmstart_ckpt="base.ckpt")
    model._trainer = _StubTrainer(ckpt_path=None)
    called = _record_warmstarts(model, monkeypatch)

    model.on_fit_start()

    assert called == [("full", "base.ckpt")]


def test_warmstart_is_skipped_when_resuming(monkeypatch) -> None:
    """The resumed weights must survive on_fit_start untouched."""
    model = _tiny_model(warmstart_ckpt="base.ckpt")
    model._trainer = _StubTrainer(ckpt_path="run/last.ckpt")
    called = _record_warmstarts(model, monkeypatch)

    model.on_fit_start()

    assert not called
    assert model._warmstart_ckpt is None


def test_vocoder_warmstart_is_skipped_when_resuming(monkeypatch) -> None:
    model = _tiny_model(vocoder_warmstart_ckpt="base.ckpt")
    model._trainer = _StubTrainer(ckpt_path="run/last.ckpt")
    called = _record_warmstarts(model, monkeypatch)

    model.on_fit_start()

    assert not called
    assert model._vocoder_warmstart_ckpt is None


def test_vocoder_warmstart_runs_on_a_fresh_fit(monkeypatch) -> None:
    model = _tiny_model(vocoder_warmstart_ckpt="base.ckpt")
    model._trainer = _StubTrainer(ckpt_path=None)
    called = _record_warmstarts(model, monkeypatch)

    model.on_fit_start()

    assert called == [("vocoder", "base.ckpt")]


def test_warmstart_does_not_re_run_on_a_second_fit(monkeypatch) -> None:
    model = _tiny_model(warmstart_ckpt="base.ckpt")
    model._trainer = _StubTrainer(ckpt_path=None)
    called = _record_warmstarts(model, monkeypatch)

    model.on_fit_start()
    model.on_fit_start()

    assert len(called) == 1
