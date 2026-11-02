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

torch = pytest.importorskip("torch")
lightning_module = pytest.importorskip("piper.train.vits.lightning")

VitsModel = lightning_module.VitsModel


class _StubTrainer:
    def __init__(self, ckpt_path: Optional[str] = None) -> None:
        self.ckpt_path = ckpt_path
        self.max_epochs = 10


def _tiny_model(num_speakers: int = 1, **kwargs) -> "VitsModel":
    return VitsModel(
        num_symbols=32,
        num_speakers=num_speakers,
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


# -- warmstarting a multi-speaker model from a single-speaker base -----------


def _save_base(model, tmp_path) -> str:
    path = tmp_path / "base.ckpt"
    torch.save({"state_dict": model.state_dict()}, path)
    return str(path)


def _synthesize(model, sid=None):
    """Deterministic audio: no sampling noise in the prior or the SDP."""
    torch.manual_seed(1)
    x = torch.randint(1, 32, (1, 12))
    lengths = torch.tensor([12])
    return model.model_g.infer(x, lengths, sid=sid, noise_scale=0.0, noise_scale_w=0.0)[
        0
    ]


def test_single_speaker_base_gives_every_speaker_the_base_voice(tmp_path):
    torch.manual_seed(0)
    base = _tiny_model(num_speakers=1).eval()
    model = _tiny_model(num_speakers=2).eval()

    model._warmstart_from_ckpt(_save_base(base, tmp_path))

    expected = _synthesize(base)
    for speaker in (0, 1):
        actual = _synthesize(model, sid=torch.tensor([speaker]))
        assert torch.allclose(actual, expected, atol=1e-6)


def test_zeroed_conditioning_still_learns(tmp_path):
    torch.manual_seed(0)
    base = _tiny_model(num_speakers=1)
    # Coupling layers initialize their output projection to zero, which makes
    # an untrained flow the identity and starves its WaveNet of gradient. A
    # trained base has non-zero ones; stand in for that.
    with torch.no_grad():
        for flow in base.model_g.flow.flows:
            if hasattr(flow, "post"):
                flow.post.weight.normal_(std=0.1)
    model = _tiny_model(num_speakers=2)
    model._warmstart_from_ckpt(_save_base(base, tmp_path))

    _synthesize(model, sid=torch.tensor([1])).sum().backward()

    generator = model.model_g
    assert generator.dec.cond.weight.grad.abs().sum() > 0
    assert generator.flow.flows[0].enc.cond_layer.weight_g.grad.abs().sum() > 0


def test_multi_speaker_base_conditioning_is_copied_not_zeroed(tmp_path):
    torch.manual_seed(0)
    base = _tiny_model(num_speakers=2)
    model = _tiny_model(num_speakers=3)

    model._warmstart_from_ckpt(_save_base(base, tmp_path))

    copied = model.model_g.dec.cond.weight
    assert torch.equal(copied, base.model_g.dec.cond.weight)
    assert copied.abs().sum() > 0
