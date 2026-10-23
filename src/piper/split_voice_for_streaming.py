"""Splits a voice ONNX model into an encoder and a decoder for streaming.

libpiper loads <model>.encoder.onnx and <model>.decoder.onnx when they are
next to <model>.onnx. It then runs the decoder in chunks and returns audio
before the whole sentence has been synthesized.

Requires the onnx package to be installed (not onnxruntime).
"""

import argparse
import logging
from pathlib import Path
from typing import Optional, Tuple

import onnx
from onnx.utils import Extractor

_LOGGER = logging.getLogger(__name__)

# Name of the latent tensor between encoder and decoder (expected by libpiper)
LATENT_NAME = "z"


def find_latent_tensor(model: onnx.ModelProto) -> str:
    """Find the tensor that is fed into the decoder (input of dec.conv_pre).

    :param model: ONNX voice model.
    :return: Name of the decoder input tensor.
    :raises ValueError: If the decoder cannot be found.
    """
    for node in model.graph.node:
        if (
            node.op_type == "Conv"
            and "conv_pre" in node.name
            and (node.name.startswith("/dec/") or "dec.conv_pre.weight" in node.input)
        ):
            return node.input[0]

    raise ValueError("Decoder input (dec.conv_pre) not found")


def _rename_tensor(graph: onnx.GraphProto, old_name: str, new_name: str) -> None:
    for node in graph.node:
        node.input[:] = [new_name if name == old_name else name for name in node.input]
        node.output[:] = [
            new_name if name == old_name else name for name in node.output
        ]

    for value_info in list(graph.input) + list(graph.output):
        if value_info.name == old_name:
            value_info.name = new_name


def split_model(
    model: onnx.ModelProto, latent_name: Optional[str] = None
) -> Tuple[onnx.ModelProto, onnx.ModelProto]:
    """Split a voice model into encoder (phoneme ids -> z) and decoder (z -> audio).

    Extra outputs of the model (e.g. alignments) become outputs of the encoder.

    :param model: ONNX voice model.
    :param latent_name: Name of the decoder input tensor (autodetected if None).
    :return: Encoder and decoder models.
    """
    if not latent_name:
        latent_name = find_latent_tensor(model)
        _LOGGER.debug("Detected decoder input: %s", latent_name)

    model = onnx.shape_inference.infer_shapes(model)
    input_names = [value_info.name for value_info in model.graph.input]
    audio_name = model.graph.output[0].name
    extra_output_names = [value_info.name for value_info in model.graph.output[1:]]

    extractor = Extractor(model)
    encoder = extractor.extract_model(input_names, [latent_name] + extra_output_names)

    decoder_inputs = [latent_name]
    if "sid" in input_names:
        decoder_inputs.append("sid")

    decoder = extractor.extract_model(decoder_inputs, [audio_name])

    _rename_tensor(encoder.graph, latent_name, LATENT_NAME)
    _rename_tensor(decoder.graph, latent_name, LATENT_NAME)

    return encoder, decoder


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("model", help="Path to ONNX voice model")
    parser.add_argument(
        "--latent-name", help="Name of the decoder input tensor (default: autodetect)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    model_path = Path(args.model)
    model = onnx.load(model_path)

    try:
        encoder, decoder = split_model(model, args.latent_name)
    except ValueError as error:
        _LOGGER.fatal("%s", error)
        return 1

    for part, part_model in (("encoder", encoder), ("decoder", decoder)):
        part_path = model_path.with_suffix(f".{part}.onnx")
        onnx.save(part_model, part_path)
        _LOGGER.info("Successfully wrote %s", part_path)

    return 0


if __name__ == "__main__":
    main()
