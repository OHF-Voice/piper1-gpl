import inspect
import logging
import pathlib
import sys

import torch
from lightning.pytorch.cli import LightningCLI

from .vits.dataset import VitsDataModule
from .vits.lightning import VitsModel

_LOGGER = logging.getLogger(__package__)

_KNOWN_MODEL_PARAMS = set(inspect.signature(VitsModel.__init__).parameters) - {"self"}


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

    def _parse_ckpt_path(self) -> None:
        if not self.config.get("subcommand"):
            return
        ckpt_path = self.config[self.config.subcommand].get("ckpt_path")
        if not (ckpt_path and pathlib.Path(ckpt_path).is_file()):
            return
        ckpt = torch.load(ckpt_path, weights_only=True, map_location="cpu")
        hparams = ckpt.get("hyper_parameters", {})
        hparams.pop("_instantiator", None)
        hparams = {k: v for k, v in hparams.items() if k in _KNOWN_MODEL_PARAMS}
        if not hparams:
            return
        if "_class_path" in hparams:
            hparams = {"class_path": hparams.pop("_class_path"), "dict_kwargs": hparams}
        hparams = {self.config.subcommand: {"model": hparams}}
        try:
            self.config = self.parser.parse_object(hparams, self.config)
        except SystemExit:
            sys.stderr.write("Parsing of ckpt_path hyperparameters failed!\n")
            raise


def main():
    logging.basicConfig(level=logging.INFO)
    torch.serialization.add_safe_globals([pathlib.PosixPath])
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.deterministic = False
    _cli = VitsLightningCLI(  # noqa: ignore=F841
        VitsModel, VitsDataModule, trainer_defaults={"max_epochs": -1}
    )


# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()
