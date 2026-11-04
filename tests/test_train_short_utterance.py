"""A clip shorter than segment_size must not break the training loss.

After VAD trimming a few clips can end up shorter than ``segment_size`` (8192
samples). With batch_size=1 the generator then produces fewer samples than the
padded reference slice, and the discriminator feature loss failed with
"The size of tensor a (8192) must match the size of tensor b (7424)" (#155).
"""

# _compute_loss is the step under test.
# pylint: disable=protected-access

from typing import Any

import pytest
import torch

lightning_module = pytest.importorskip("piper.train.vits.lightning")
dataset_module = pytest.importorskip("piper.train.vits.dataset")
# The training step aligns with the Cython extension from build_monotonic_align.sh
pytest.importorskip("piper.train.vits.monotonic_align")


def _tiny_model(use_mrd: bool) -> Any:
    return lightning_module.VitsModel(
        use_mrd=use_mrd,
        num_symbols=32,
        num_speakers=1,
        inter_channels=16,
        hidden_channels=16,
        filter_channels=32,
        n_layers=2,
        upsample_initial_channel=16,
        mos_metric=None,
    )


@pytest.mark.parametrize("use_mrd", [False, True])
@pytest.mark.parametrize("frames", [29, 16])
def test_loss_on_a_clip_shorter_than_segment_size(frames: int, use_mrd: bool) -> None:
    torch.manual_seed(0)
    model = _tiny_model(use_mrd)
    hop = model.hparams.hop_length
    assert frames * hop < model.hparams.segment_size

    utterance = dataset_module.UtteranceTensors(
        phoneme_ids=torch.LongTensor([1, 2, 3, 4, 5]),
        spectrogram=torch.rand(model.hparams.filter_length // 2 + 1, frames),
        audio_norm=torch.rand(frames * hop) * 2 - 1,
    )
    collate = dataset_module.UtteranceCollate(
        is_multispeaker=False, segment_size=model.hparams.segment_size
    )

    loss_g, loss_d, metrics = model._compute_loss(collate([utterance]))

    for value in [loss_g, loss_d, *metrics.values()]:
        assert torch.isfinite(torch.as_tensor(value)).all()
