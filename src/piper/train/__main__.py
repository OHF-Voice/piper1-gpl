import logging
import sys
from pathlib import Path

import torch
from lightning.pytorch.cli import LightningCLI

from .checkpoint import clean_checkpoint
from .vits.dataset import VitsDataModule
from .vits.lightning import VitsModel

_LOGGER = logging.getLogger(__package__)



def _process_checkpoint_cleaning():
    """Clean checkpoint and convert --ckpt_path to --model.pretrained_ckpt.

    When --clean_checkpoint is specified, the checkpoint is treated as pretrained
    weights only (not a training resume), allowing cross-architecture loading
    such as single-speaker -> multi-speaker conversion.
    """
    sys.argv.remove("--clean_checkpoint")
    try:
        idx = sys.argv.index("--ckpt_path")
        ckpt_path = Path(sys.argv[idx + 1])
    except (ValueError, IndexError):
        return
    if not ckpt_path.exists():
        return

    num_speakers = 1
    try:
        ns_idx = sys.argv.index("--model.num_speakers")
        num_speakers = int(sys.argv[ns_idx + 1])
    except (ValueError, IndexError):
        pass

    cleaned_path = clean_checkpoint(ckpt_path, num_speakers)

    # Replace --ckpt_path with --model.vocoder_warmstart_ckpt so Lightning loads
    # weights only instead of resuming training state
    sys.argv[idx] = "--model.vocoder_warmstart_ckpt"
    sys.argv[idx + 1] = cleaned_path
    sys.argv.append("--model.warmstart_pretrained")
    sys.argv.append("true")


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

    if "--clean_checkpoint" in sys.argv:
        _process_checkpoint_cleaning()

    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.deterministic = False

    _cli = VitsLightningCLI(  # noqa: ignore=F841
        VitsModel, VitsDataModule, trainer_defaults={"max_epochs": -1}
    )


# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()
