"""Tests for splitting voices for streaming."""

import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")

# pylint: disable=wrong-import-position
from onnx import TensorProto, helper  # noqa: E402

from piper.split_voice_for_streaming import LATENT_NAME, split_model  # noqa: E402


def _make_voice(with_alignments: bool = False) -> "onnx.ModelProto":
    """Tiny voice-like model: phoneme ids -> latent -> dec.conv_pre -> audio."""
    nodes = [
        helper.make_node("Cast", ["input"], ["ids_float"], to=TensorProto.FLOAT),
        helper.make_node("Mul", ["ids_float", "scale"], ["scaled"]),
        helper.make_node("Unsqueeze", ["scaled", "axes"], ["/Mul_7_output_0"]),
        helper.make_node(
            "Conv",
            ["/Mul_7_output_0", "dec.conv_pre.weight"],
            ["/dec/conv_pre/Conv_output_0"],
            name="/dec/conv_pre/Conv",
            pads=[1, 1],
        ),
        helper.make_node("Tanh", ["/dec/conv_pre/Conv_output_0"], ["output"]),
    ]
    outputs = [helper.make_tensor_value_info("output", TensorProto.FLOAT, None)]
    if with_alignments:
        nodes.append(helper.make_node("Ceil", ["ids_float"], ["w_ceil"]))
        outputs.append(helper.make_tensor_value_info("w_ceil", TensorProto.FLOAT, None))

    graph = helper.make_graph(
        nodes,
        "voice",
        [
            helper.make_tensor_value_info("input", TensorProto.INT64, [1, None]),
            helper.make_tensor_value_info("input_lengths", TensorProto.INT64, [1]),
            helper.make_tensor_value_info("scales", TensorProto.FLOAT, [3]),
        ],
        outputs,
        initializer=[
            helper.make_tensor("scale", TensorProto.FLOAT, [], [0.1]),
            helper.make_tensor("axes", TensorProto.INT64, [1], [1]),
            helper.make_tensor(
                "dec.conv_pre.weight", TensorProto.FLOAT, [1, 1, 3], [0.2, 0.5, 0.3]
            ),
        ],
    )
    return helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 15)], ir_version=8
    )


def _run(model: "onnx.ModelProto", feeds: dict) -> list:
    session = ort.InferenceSession(
        model.SerializeToString(), providers=["CPUExecutionProvider"]
    )
    input_names = {i.name for i in session.get_inputs()}
    return session.run(None, {k: v for k, v in feeds.items() if k in input_names})


def test_split_matches_full_model() -> None:
    """Encoder followed by decoder gives the same audio as the full model."""
    voice = _make_voice()
    feeds = {
        "input": np.array([[1, 0, 5, 0, 9, 0, 2]], dtype=np.int64),
        "input_lengths": np.array([7], dtype=np.int64),
        "scales": np.array([0.667, 1.0, 0.8], dtype=np.float32),
    }

    encoder, decoder = split_model(voice)

    assert [o.name for o in encoder.graph.output] == [LATENT_NAME]
    assert [i.name for i in decoder.graph.input] == [LATENT_NAME]

    (expected,) = _run(voice, feeds)
    (latent,) = _run(encoder, feeds)
    (audio,) = _run(decoder, {LATENT_NAME: latent})
    np.testing.assert_allclose(audio, expected)


def test_split_keeps_alignments() -> None:
    """Alignment output of a patched voice is moved to the encoder."""
    encoder, decoder = split_model(_make_voice(with_alignments=True))

    assert [o.name for o in encoder.graph.output] == [LATENT_NAME, "w_ceil"]
    assert [o.name for o in decoder.graph.output] == ["output"]


def test_split_without_decoder() -> None:
    """Models without a decoder are rejected."""
    voice = _make_voice()
    for node in voice.graph.node:
        node.name = ""

    with pytest.raises(ValueError):
        split_model(voice)
