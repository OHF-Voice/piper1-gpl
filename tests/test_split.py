"""Tests for piper.split and streaming (chunked) decoding.

Piper voices are not bundled with the repo, so these tests build a miniature
VITS-shaped ONNX model by hand: a trivial "encoder" producing a latent, and a
convolutional "decoder" under the /dec/ namespace with a real receptive field
(Conv -> ConvTranspose upsampler -> Conv), mirroring how a torch export names
a `self.dec` submodule. The conditioned variant adds what a multi-speaker
voice has: a speaker embedding crossing into the decoder as a second boundary
tensor. That is enough to exercise the boundary finder, the split, and the
exactness of overlapped-chunk decoding against the monolithic output.
"""

from pathlib import Path

import numpy as np
import onnx
import onnxruntime
import pytest
from onnx import TensorProto, helper, numpy_helper

from piper.split import find_decoder_inputs, split_voice
from piper.voice import _iter_decoded_chunks

_CHANNELS = 8
_HIDDEN = 16
_UPSAMPLE = 4  # hop: samples per latent frame


def _make_vits_like_model(path: Path, conditioned: bool = False) -> None:
    """Build input -> /flow/Mul -> /dec/ conv stack -> output; with
    conditioned=True a speaker-embedding-like tensor also crosses into the
    decoder (broadcast-added after conv_pre), as in multi-speaker voices."""
    rng = np.random.default_rng(0)

    def weight(name, *shape):
        return numpy_helper.from_array(
            rng.standard_normal(shape).astype(np.float32) * 0.3, name
        )

    up_input = "/dec/conv_pre/Conv_output_0"
    nodes = [
        helper.make_node(
            "Mul", ["input", "one"], ["/flow/Mul_output_0"], name="/flow/Mul"
        ),
        helper.make_node(
            "Conv",
            ["/flow/Mul_output_0", "dec.conv_pre.weight", "dec.conv_pre.bias"],
            ["/dec/conv_pre/Conv_output_0"],
            name="/dec/conv_pre/Conv",
            pads=[3, 3],
        ),
    ]
    inputs = [
        helper.make_tensor_value_info(
            "input", TensorProto.FLOAT, ["batch_size", _CHANNELS, "frames"]
        )
    ]
    if conditioned:
        inputs.append(
            helper.make_tensor_value_info(
                "g", TensorProto.FLOAT, ["batch_size", _HIDDEN, 1]
            )
        )
        nodes.append(
            helper.make_node(
                "Mul", ["g", "one"], ["/spk/Mul_output_0"], name="/spk/Mul"
            )
        )
        nodes.append(
            helper.make_node(
                "Add",
                ["/dec/conv_pre/Conv_output_0", "/spk/Mul_output_0"],
                ["/dec/cond/Add_output_0"],
                name="/dec/cond/Add",
            )
        )
        up_input = "/dec/cond/Add_output_0"

    nodes += [
        helper.make_node(
            "ConvTranspose",
            [up_input, "dec.ups.0.weight", "dec.ups.0.bias"],
            ["/dec/ups.0/ConvTranspose_output_0"],
            name="/dec/ups.0/ConvTranspose",
            kernel_shape=[8],
            strides=[_UPSAMPLE],
            pads=[2, 2],
        ),
        helper.make_node(
            "LeakyRelu",
            ["/dec/ups.0/ConvTranspose_output_0"],
            ["/dec/LeakyRelu_output_0"],
            name="/dec/LeakyRelu",
            alpha=0.1,
        ),
        helper.make_node(
            "Conv",
            ["/dec/LeakyRelu_output_0", "dec.conv_post.weight", "dec.conv_post.bias"],
            ["/dec/conv_post/Conv_output_0"],
            name="/dec/conv_post/Conv",
            pads=[3, 3],
        ),
        helper.make_node(
            "Tanh", ["/dec/conv_post/Conv_output_0"], ["output"], name="/dec/Tanh"
        ),
    ]
    graph = helper.make_graph(
        nodes,
        "vits_like",
        inputs=inputs,
        outputs=[
            helper.make_tensor_value_info(
                "output", TensorProto.FLOAT, ["batch_size", 1, "samples"]
            )
        ],
        initializer=[
            numpy_helper.from_array(np.float32(1.0), "one"),
            weight("dec.conv_pre.weight", _HIDDEN, _CHANNELS, 7),
            weight("dec.conv_pre.bias", _HIDDEN),
            weight("dec.ups.0.weight", _HIDDEN, _HIDDEN, 8),
            weight("dec.ups.0.bias", _HIDDEN),
            weight("dec.conv_post.weight", 1, _HIDDEN, 7),
            weight("dec.conv_post.bias", 1),
        ],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 15)]
    )
    model.ir_version = 8
    onnx.save(model, str(path))


def test_find_decoder_inputs(tmp_path: Path) -> None:
    """The tensors crossing into /dec/ are found, the latent first."""
    model_path = tmp_path / "voice.onnx"
    _make_vits_like_model(model_path)
    assert find_decoder_inputs(onnx.load(str(model_path))) == ["/flow/Mul_output_0"]

    _make_vits_like_model(model_path, conditioned=True)
    assert find_decoder_inputs(onnx.load(str(model_path))) == [
        "/flow/Mul_output_0",
        "/spk/Mul_output_0",
    ]


def test_find_decoder_inputs_requires_dec(tmp_path: Path) -> None:
    """A graph without a /dec/ namespace is rejected."""
    graph = helper.make_graph(
        [helper.make_node("Identity", ["input"], ["output"], name="/enc/Identity")],
        "no_dec",
        inputs=[helper.make_tensor_value_info("input", TensorProto.FLOAT, [1])],
        outputs=[helper.make_tensor_value_info("output", TensorProto.FLOAT, [1])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 15)])
    with pytest.raises(ValueError):
        find_decoder_inputs(model)


def test_split_and_chunked_decode_exact(tmp_path: Path) -> None:
    """Chunked decoding with enough overlap equals the monolithic decode."""
    model_path = tmp_path / "voice.onnx"
    _make_vits_like_model(model_path)
    enc_path, dec_path = split_voice(model_path)
    assert enc_path == tmp_path / "voice.enc.onnx"
    assert dec_path == tmp_path / "voice.dec.onnx"

    rng = np.random.default_rng(1)
    z = rng.standard_normal((1, _CHANNELS, 64)).astype(np.float32)

    enc_session = onnxruntime.InferenceSession(
        str(enc_path), providers=["CPUExecutionProvider"]
    )
    dec_session = onnxruntime.InferenceSession(
        str(dec_path), providers=["CPUExecutionProvider"]
    )

    # enc half reproduces the boundary tensor
    z_name = enc_session.get_outputs()[0].name
    latent = enc_session.run([z_name], {"input": z})[0]
    assert np.array_equal(latent, z)  # the mini "flow" is Mul by 1.0

    reference = dec_session.run(["output"], {z_name: latent})[0].reshape(-1)
    assert reference.shape[0] == 64 * _UPSAMPLE

    # uneven chunk size on purpose: exercises the final short chunk
    chunks = list(_iter_decoded_chunks(dec_session, latent, 7, 8))
    audio = np.concatenate(chunks)
    assert audio.shape == reference.shape
    assert np.allclose(audio, reference, atol=1e-6)

    # too little overlap must NOT match: proves the test can fail
    audio_bad = np.concatenate(list(_iter_decoded_chunks(dec_session, latent, 7, 0)))
    assert not np.allclose(audio_bad, reference, atol=1e-6)


def test_conditioned_split_and_chunked_decode(tmp_path: Path) -> None:
    """A multi-speaker-shaped voice: the speaker embedding crosses into the
    decoder as a second boundary, is carried by the encoder half, and is fed
    whole to every chunk — chunked still equals monolithic."""
    model_path = tmp_path / "voice.onnx"
    _make_vits_like_model(model_path, conditioned=True)
    enc_path, dec_path = split_voice(model_path)

    enc_session = onnxruntime.InferenceSession(
        str(enc_path), providers=["CPUExecutionProvider"]
    )
    dec_session = onnxruntime.InferenceSession(
        str(dec_path), providers=["CPUExecutionProvider"]
    )

    rng = np.random.default_rng(2)
    z = rng.standard_normal((1, _CHANNELS, 64)).astype(np.float32)
    g = rng.standard_normal((1, _HIDDEN, 1)).astype(np.float32)

    enc_outputs = [o.name for o in enc_session.get_outputs()]
    dec_inputs = [i.name for i in dec_session.get_inputs()]
    assert dec_inputs == ["/flow/Mul_output_0", "/spk/Mul_output_0"]

    by_name = dict(zip(enc_outputs, enc_session.run(enc_outputs, {"input": z, "g": g})))
    latent = by_name[dec_inputs[0]]
    conditioning = {n: by_name[n] for n in dec_inputs[1:]}

    reference = dec_session.run(
        ["output"], dict({dec_inputs[0]: latent}, **conditioning)
    )[0].reshape(-1)
    audio = np.concatenate(
        list(_iter_decoded_chunks(dec_session, latent, 7, 8, conditioning))
    )
    assert audio.shape == reference.shape
    assert np.allclose(audio, reference, atol=1e-6)

    # the conditioning matters: a different speaker embedding changes the audio
    other = dict(
        zip(enc_outputs, enc_session.run(enc_outputs, {"input": z, "g": g + 1.0}))
    )
    changed = dec_session.run(
        ["output"],
        {dec_inputs[0]: other[dec_inputs[0]], dec_inputs[1]: other[dec_inputs[1]]},
    )[0].reshape(-1)
    assert not np.allclose(changed, reference, atol=1e-3)
