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


def find_decoder_inputs(model) -> list:
    """
    Find the tensors that cross from the encoder side into the decoder — the
    masked latent z FIRST, then any conditioning (a multi-speaker voice also
    feeds the decoder its speaker embedding).

    :param model: Loaded ONNX ModelProto of a Piper VITS voice.
    :return: Boundary tensor names, the latent first.
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

    conv_pre = next(
        node for node in decoder_nodes if node.op_type == "Conv"
    )
    z_name = conv_pre.input[0]
    if z_name not in boundary:
        raise ValueError(f"Decoder input conv feeds from {z_name}, not a boundary?")

    return [z_name] + sorted(boundary - {z_name})


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
    boundaries = find_decoder_inputs(model)
    _LOGGER.debug("Decoder boundary tensors: %s", boundaries)

    # The boundary tensors need value_info entries for the Extractor (older
    # exports never ran shape inference over them). The latent's channel
    # count comes from conv_pre's weight; conditioning shapes stay symbolic.
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
    known = {vi.name for vi in model.graph.value_info}
    for name in boundaries:
        if name in known:
            continue
        if name == boundaries[0]:
            vi = helper.make_tensor_value_info(
                name, TensorProto.FLOAT, ["batch_size", z_channels, "z_time"]
            )
        else:
            vi = helper.make_tensor_value_info(name, TensorProto.FLOAT, None)
        model.graph.value_info.append(vi)

    extractor = onnx.utils.Extractor(model)
    graph_inputs = [graph_input.name for graph_input in model.graph.input]
    encoder = extractor.extract_model(graph_inputs, boundaries)
    decoder = extractor.extract_model(boundaries, ["output"])

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
