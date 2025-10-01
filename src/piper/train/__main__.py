import logging

import inspect
import tempfile
import argparse

import torch
from lightning.pytorch.cli import LightningCLI

from .vits.dataset import VitsDataModule
from .vits.lightning import VitsModel

_LOGGER = logging.getLogger(__package__)


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
    parser = argparse.ArgumentParser(description="VITS Lightning CLI with checkpoint cleaning")
    parser.add_argument("--ckpt_path", type=str, help="Path to the checkpoint file to clean")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.deterministic = False

    if args.ckpt_path:
        cleaned_ckpt_path = clean_checkpoint(args.ckpt_path)
    else:
        cleaned_ckpt_path = None
        _LOGGER.info("No checkpoint path provided; skipping checkpoint cleaning.")

    _cli = VitsLightningCLI(  # noqa: ignore=F841
        VitsModel, VitsDataModule, trainer_defaults={"max_epochs": -1}, args={"ckpt_path": cleaned_ckpt_path} if cleaned_ckpt_path else {}
    )


# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()
