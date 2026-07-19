import logging

import inspect
import tempfile
import sys

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


def clean_checkpoint(checkpoint_path):
    checkpoint = torch.load(checkpoint_path, weights_only=False, map_location="cpu")

    if "hyper_parameters" not in checkpoint:
        return checkpoint_path

    init_signature = inspect.signature(VitsModel.__init__)
    valid_params = set(init_signature.parameters.keys())
    checkpoint_params = set(checkpoint["hyper_parameters"].keys())
    invalid_params = checkpoint_params - valid_params

    if not invalid_params:
        return checkpoint_path

    for param in invalid_params:
        _LOGGER.info(f"Removing invalid parameter '{param}' from checkpoint")
        del checkpoint["hyper_parameters"][param]

    temp_file = tempfile.NamedTemporaryFile(suffix=".ckpt", delete=False)
    torch.save(checkpoint, temp_file.name)
    temp_file.close()

    _LOGGER.info(f"Created cleaned checkpoint: {temp_file.name}")
    return temp_file.name

def main():
    
    logging.basicConfig(level=logging.INFO)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.deterministic = False

    ckpt_path = None
    if '--ckpt_path' in sys.argv:
        try:
            ckpt_idx = sys.argv.index('--ckpt_path')
            if ckpt_idx + 1 < len(sys.argv):
                ckpt_path = sys.argv[ckpt_idx + 1]
        except (IndexError, ValueError):
            pass

    if ckpt_path:
        cleaned_ckpt_path = clean_checkpoint(ckpt_path)
        # issue a ckpt path replacement to fixed ckpt path
        if '--ckpt_path' in sys.argv:
            ckpt_idx = sys.argv.index('--ckpt_path')
            if ckpt_idx + 1 < len(sys.argv):
                sys.argv[ckpt_idx + 1] = cleaned_ckpt_path

    else:
        _LOGGER.info("No checkpoint path provided; skipping checkpoint cleaning.")

    _cli = VitsLightningCLI(  # noqa: ignore=F841
        VitsModel,
        VitsDataModule,
        trainer_defaults={"max_epochs": -1, "callbacks": _DEFAULT_CALLBACKS},
    )


# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()
