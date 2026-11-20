#!/usr/bin/env python3

import argparse
import logging
from pathlib import Path

import torch

from .vits.lightning import VitsModel

_LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Main entry point"""
    torch.manual_seed(1234)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint", required=True, help="Path to model checkpoint (.ckpt)"
    )
    parser.add_argument("--generator", required=True, help="Path to output file (.pt)")

    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG messages to the console"
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    _LOGGER.debug(args)

    # -------------------------------------------------------------------------

    generator_path = Path(args.generator)
    generator_path.parent.mkdir(parents=True, exist_ok=True)

    checkpoint_path = Path(args.checkpoint)

    # pylint: disable=no-value-for-parameter
    model = VitsModel.load_from_checkpoint(checkpoint_path, map_location="cpu")
    model_g = model.model_g

    # Inference only
    model_g.eval()

    with torch.no_grad():
        model_g.dec.remove_weight_norm()

    model_g.forward = model_g.infer  # type: ignore[method-assign,assignment]

    torch.save(model_g, generator_path)
    _LOGGER.info("Exported generator to %s", generator_path)


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
