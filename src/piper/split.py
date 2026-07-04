"""Split a VITS voice model for streaming synthesis.

A Piper voice is exported as a single ONNX graph: the text encoder, duration
predictor, and flow (which must see the whole utterance -- prosody is global)
followed by the HiFi-GAN decoder that turns latent frames into waveform
samples. The decoder dominates inference time but is a pure convolutional
network with a finite receptive field, so it can be run in overlapped chunks
whose interiors match the monolithic output exactly -- audio can start
playing after the first chunk instead of after the whole utterance.

This module splits a voice at the single tensor that crosses into the
decoder (the masked latent feeding the decoder's input convolution), writing
``<voice>.enc.onnx`` and ``<voice>.dec.onnx`` next to the original.
``PiperVoice.load(..., streaming=True)`` picks them up for
``synthesize_stream()``.

Splitting requires the ``onnx`` package (synthesis does not):

    python3 -m piper.split /path/to/voice.onnx
"""

import argparse
import logging
from pathlib import Path
from typing import Tuple, Union

_LOGGER = logging.getLogger(__name__)

_DECODER_PREFIX = "/dec/"


def find_decoder_input(model) -> str:
    """
    Find the one tensor that crosses from the encoder side into the decoder.

    :param model: Loaded ONNX ModelProto of a Piper VITS voice.
    :return: Name of the boundary tensor (the masked latent z).
    """
    graph = model.graph
    producers = {
        output: node for node in graph.node for output in node.output
    }
    initializers = {tensor.name for tensor in graph.initializer}

    decoder_nodes = [
        node for node in graph.node if node.name.startswith(_DECODER_PREFIX)
    ]
    if not decoder_nodes:
        raise ValueError(
            f"No {_DECODER_PREFIX} nodes in graph: not a Piper VITS export?"
        )

    boundary = set()
    for node in decoder_nodes:
        for input_name in node.input:
            if (not input_name) or (input_name in initializers):
                continue

            producer = producers.get(input_name)
            if (producer is not None) and (
                not producer.name.startswith(_DECODER_PREFIX)
            ):
                boundary.add(input_name)

    if len(boundary) != 1:
        raise ValueError(
            f"Expected exactly one tensor crossing into the decoder, found: {boundary}"
        )

    return boundary.pop()


def split_voice(
    model_path: Union[str, Path],
    output_dir: Union[str, Path, None] = None,
) -> Tuple[Path, Path]:
    """
    Split a voice model into encoder and decoder halves for streaming.

    :param model_path: Path to voice ONNX file.
    :param output_dir: Directory for the halves (default: next to the voice).
    :return: Paths of (encoder, decoder) ONNX files.
    """
    try:
        import onnx
        import onnx.utils
        from onnx import TensorProto, helper
    except ImportError as err:
        raise ImportError(
            "Splitting requires the onnx package: pip install onnx"
        ) from err

    model_path = Path(model_path)
    if output_dir is None:
        output_dir = model_path.parent

    output_dir = Path(output_dir)
    enc_path = output_dir / model_path.with_suffix(".enc.onnx").name
    dec_path = output_dir / model_path.with_suffix(".dec.onnx").name

    model = onnx.load(str(model_path))
    z_name = find_decoder_input(model)

    # conv_pre's weight gives the latent channel count for the boundary's
    # value_info (older exports never ran shape inference over it).
    conv_pre = next(
        node
        for node in model.graph.node
        if node.name.startswith(_DECODER_PREFIX) and node.op_type == "Conv"
    )
    conv_pre_weight = next(
        tensor
        for tensor in model.graph.initializer
        if tensor.name == conv_pre.input[1]
    )
    z_channels = conv_pre_weight.dims[1]
    _LOGGER.debug("Boundary %s, %s latent channels", z_name, z_channels)

    if not any(vi.name == z_name for vi in model.graph.value_info):
        model.graph.value_info.append(
            helper.make_tensor_value_info(
                z_name, TensorProto.FLOAT, ["batch_size", z_channels, "z_time"]
            )
        )

    extractor = onnx.utils.Extractor(model)
    graph_inputs = [graph_input.name for graph_input in model.graph.input]
    encoder = extractor.extract_model(graph_inputs, [z_name])
    decoder = extractor.extract_model([z_name], ["output"])

    onnx.save(encoder, str(enc_path))
    onnx.save(decoder, str(dec_path))

    return enc_path, dec_path


def main() -> None:
    """Split voices for streaming synthesis."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", nargs="+", help="Path to voice ONNX file(s)")
    parser.add_argument(
        "-o",
        "--output-dir",
        "--output_dir",
        help="Directory for the split halves (default: next to each voice)",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG messages to console"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    for model in args.model:
        enc_path, dec_path = split_voice(model, args.output_dir)
        print(enc_path)
        print(dec_path)


if __name__ == "__main__":
    main()
