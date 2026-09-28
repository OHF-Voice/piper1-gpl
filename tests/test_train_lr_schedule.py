"""Tests for the VITS learning-rate schedule.

The regression these guard against: ``VitsModel`` sets
``automatic_optimization = False``, and under manual optimization Lightning does
not step the schedulers returned by ``configure_optimizers``. For a long time
nothing else stepped them either, so every Piper model -- base and finetune
alike -- trained at a flat learning rate from first step to last. Checkpoints
from that era all report ``lr_schedulers`` ``last_epoch=0`` regardless of how
many epochs they ran.
"""

# Reaching for _trainer and the module's upstream-gamma constants is
# deliberate: both are exactly what this module is asserting about.
# pylint: disable=protected-access

from typing import Optional

import pytest

lightning_module = pytest.importorskip("piper.train.vits.lightning")

VitsModel = lightning_module.VitsModel
UPSTREAM_LR_DECAY = lightning_module._UPSTREAM_LR_DECAY
UPSTREAM_LR_DECAY_D = lightning_module._UPSTREAM_LR_DECAY_D


class _StubTrainer:
    """Stands in for the bits of Trainer that the LR schedule reads."""

    def __init__(self, max_epochs: Optional[int]) -> None:
        self.max_epochs = max_epochs


def _tiny_model(max_epochs: Optional[int] = 100, **kwargs) -> "VitsModel":
    """A VitsModel small enough to build quickly on CPU.

    upsample_rates is left alone so its product still matches hop_length.
    """
    model = VitsModel(
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
    model._trainer = _StubTrainer(max_epochs) if max_epochs is not None else None
    return model


def test_lr_decay_derived_from_max_epochs() -> None:
    """An unset gamma anneals to lr_final_ratio over the whole run."""
    model = _tiny_model(max_epochs=100, lr_final_ratio=0.05)
    _optimizers, schedulers = model.configure_optimizers()

    expected = 0.05 ** (1.0 / 100)
    assert schedulers[0].gamma == pytest.approx(expected)
    assert schedulers[1].gamma == pytest.approx(expected)

    # The point of deriving it: the LR really does land on the target.
    assert expected**100 == pytest.approx(0.05)


def test_derived_lr_decay_tracks_run_length() -> None:
    """A longer run gets a gentler gamma, not the same one."""
    short = _tiny_model(max_epochs=50).configure_optimizers()[1][0].gamma
    long = _tiny_model(max_epochs=500).configure_optimizers()[1][0].gamma
    assert short < long < 1.0


def test_explicit_lr_decay_is_respected() -> None:
    """Passing a gamma explicitly opts out of derivation entirely."""
    model = _tiny_model(max_epochs=100, lr_decay=0.5, lr_decay_d=0.25)
    _optimizers, schedulers = model.configure_optimizers()
    assert schedulers[0].gamma == pytest.approx(0.5)
    assert schedulers[1].gamma == pytest.approx(0.25)


def test_open_ended_run_falls_back_to_upstream_gamma() -> None:
    """With max_epochs=-1 there is no run length to anneal over."""
    model = _tiny_model(max_epochs=-1)
    _optimizers, schedulers = model.configure_optimizers()
    assert schedulers[0].gamma == pytest.approx(UPSTREAM_LR_DECAY)
    assert schedulers[1].gamma == pytest.approx(UPSTREAM_LR_DECAY_D)


def test_lr_final_ratio_of_one_keeps_lr_constant() -> None:
    """Explicit opt-out for anyone who wants the old flat-LR behavior."""
    model = _tiny_model(max_epochs=100, lr_final_ratio=1.0)
    _optimizers, schedulers = model.configure_optimizers()
    assert schedulers[0].gamma == pytest.approx(1.0)


def test_invalid_lr_final_ratio_raises() -> None:
    for bad in (0.0, -0.1, 1.5):
        model = _tiny_model(max_epochs=100, lr_final_ratio=bad)
        with pytest.raises(ValueError, match="lr_final_ratio"):
            model.configure_optimizers()


def test_on_train_epoch_end_steps_the_schedulers() -> None:
    """The regression test: the schedulers must not be inert.

    Before the fix, ``on_train_epoch_end`` did not exist and nothing advanced
    the schedule, so ``last_epoch`` stayed at 0 and the LR never moved.
    """
    model = _tiny_model(max_epochs=10, lr_final_ratio=0.05)
    optimizers, schedulers = model.configure_optimizers()
    gamma = schedulers[0].gamma
    initial_lr = optimizers[0].param_groups[0]["lr"]

    # Stand in for Lightning's own lr_schedulers() accessor, which needs a
    # real Trainer. Everything else here is the production code path.
    model.lr_schedulers = lambda: schedulers  # type: ignore[method-assign]

    # Detach the stub trainer so self.log() short-circuits (it no-ops with a
    # warning when no Trainer is attached) instead of reaching into loop
    # internals the stub does not have. Scheduler stepping is unaffected.
    model._trainer = None

    for epoch in range(1, 6):
        model.on_train_epoch_end()
        assert schedulers[0].last_epoch == epoch
        assert optimizers[0].param_groups[0]["lr"] == pytest.approx(
            initial_lr * (gamma**epoch)
        )

    assert optimizers[0].param_groups[0]["lr"] < initial_lr


def test_restored_gamma_does_not_override_the_configured_one() -> None:
    """Resuming an older run must not silently discard the derived anneal.

    ExponentialLR.state_dict() carries gamma and load_state_dict() is a plain
    __dict__.update(), so a checkpoint written with the upstream constant will
    overwrite whatever configure_optimizers resolved.
    """
    model = _tiny_model(max_epochs=100, lr_final_ratio=0.05)
    _optimizers, schedulers = model.configure_optimizers()
    derived = schedulers[0].gamma
    assert derived != pytest.approx(UPSTREAM_LR_DECAY)

    # Simulate Lightning restoring scheduler state from an older checkpoint.
    for scheduler, stale in zip(schedulers, (UPSTREAM_LR_DECAY, UPSTREAM_LR_DECAY_D)):
        state = scheduler.state_dict()
        state["gamma"] = stale
        scheduler.load_state_dict(state)
    assert schedulers[0].gamma == pytest.approx(UPSTREAM_LR_DECAY)

    model.lr_schedulers = lambda: schedulers  # type: ignore[method-assign]
    model.on_train_start()

    assert schedulers[0].gamma == pytest.approx(derived)
    assert schedulers[1].gamma == pytest.approx(
        model._resolved_gammas[1]  # noqa: SLF001
    )


def test_on_train_start_before_configure_optimizers_is_a_noop() -> None:
    model = _tiny_model(max_epochs=10)
    model.lr_schedulers = lambda: None  # type: ignore[method-assign]
    model.on_train_start()  # must not raise


def test_on_train_epoch_end_without_schedulers_is_a_noop() -> None:
    """lr_schedulers() returns None before the trainer has set them up."""
    model = _tiny_model(max_epochs=10)
    model.lr_schedulers = lambda: None  # type: ignore[method-assign]
    model.on_train_epoch_end()  # must not raise
