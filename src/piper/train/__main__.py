import logging

import torch
from lightning.pytorch.callbacks import ModelCheckpoint
from lightning.pytorch.cli import LightningCLI

from .vits.dataset import VitsDataModule
from .vits.lightning import VitsModel

_LOGGER = logging.getLogger(__package__)

# Checkpoint-selection signal. The raw mel L1 ("val_mel") tracks reconstruction
# fidelity and trends down as the model improves, so it is a reasonable key for
# keeping the best checkpoints. It is NOT, however, used to stop training: mel
# L1 saturates early in VITS while the adversarial (GAN) losses keep removing
# audible artifacts, so an early-stop on val_mel fires well before the audio is
# clean. Instead we train on a fixed/open-ended schedule and let the user pick a
# final checkpoint by listening (and/or by "val_mos"). Override from the
# LightningCLI config if you want different behavior.
_MONITOR = "val_mel"

_DEFAULT_CALLBACKS = [
    ModelCheckpoint(
        monitor=_MONITOR,
        mode="min",
        save_top_k=5,
        save_last=True,
        filename="epoch={epoch}-val_mel={val_mel:.4f}",
        auto_insert_metric_name=False,
    ),
    # Also keep the best-by-perceptual-quality checkpoints. "val_mos" (UTMOS)
    # tracks audible artifacts that mel L1 misses, so its winner is often the
    # better-sounding model. If the MOS predictor can't be loaded, val_mos is
    # never logged and this callback simply finds nothing to save (Lightning
    # warns once and skips) -- it does not interfere with the val_mel/last
    # checkpoints above. No save_last here to avoid clobbering last.ckpt.
    ModelCheckpoint(
        monitor="val_mos",
        mode="max",
        save_top_k=5,
        save_last=False,
        filename="epoch={epoch}-val_mos={val_mos:.4f}",
        auto_insert_metric_name=False,
    ),
]


class VitsLightningCLI(LightningCLI):
    def add_arguments_to_parser(self, parser):
        parser.link_arguments("data.batch_size", "model.batch_size")
        parser.link_arguments("data.num_symbols", "model.num_symbols")
        parser.link_arguments("model.num_speakers", "data.num_speakers")
        parser.link_arguments("model.sample_rate", "data.sample_rate")
        parser.link_arguments("model.filter_length", "data.filter_length")
        parser.link_arguments("model.hop_length", "data.hop_length")
        parser.link_arguments("model.win_length", "data.win_length")
        parser.link_arguments("model.segment_size", "data.segment_size")


def main():
    logging.basicConfig(level=logging.INFO)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.deterministic = False
    _cli = VitsLightningCLI(  # noqa: ignore=F841
        VitsModel,
        VitsDataModule,
        trainer_defaults={"max_epochs": -1, "callbacks": _DEFAULT_CALLBACKS},
    )


# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()
