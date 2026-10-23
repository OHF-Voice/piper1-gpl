"""Tests for Piper."""

import io
import shutil
import struct
import sys
import wave
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from piper import PiperVoice
from piper.const import BOS, EOS
from piper.phonemize_espeak import EspeakPhonemizer

from . import EN_US_VOWEL_CLUSTERS

_DIR = Path(__file__).parent
_TESTS_DIR = _DIR
_TEST_VOICE = _TESTS_DIR / "test_voice.onnx"
_TEST_CONFIG = _TESTS_DIR / "test_voice.onnx.json"


def test_load_voice() -> None:
    """Test loading a voice that generates silence."""
    voice = PiperVoice.load(_TEST_VOICE)
    assert voice.config.sample_rate == 22050
    assert voice.config.num_symbols == 256
    assert voice.config.num_speakers == 1
    assert voice.config.phoneme_type == "espeak"
    assert voice.config.espeak_voice == "en-us"


def test_load_voice_cuda_preloads_dlls() -> None:
    """Test that use_cuda=True calls preload_dlls before creating InferenceSession."""
    call_order: list[str] = []

    def fake_preload() -> None:
        call_order.append("preload")

    def fake_session(*args: Any, **kwargs: Any) -> MagicMock:
        call_order.append("session")
        return MagicMock()

    with (
        patch(
            "piper.voice.onnxruntime.preload_dlls",
            side_effect=fake_preload,
            create=True,
        ) as mock_preload,
        patch(
            "piper.voice.onnxruntime.InferenceSession",
            side_effect=fake_session,
        ) as mock_session,
    ):
        PiperVoice.load(_TEST_VOICE, use_cuda=True)
        assert mock_preload.call_count == 1
        assert mock_session.call_count == 1
        assert call_order == ["preload", "session"]
        _args, kwargs = mock_session.call_args
        assert kwargs["providers"] == [
            (
                "CUDAExecutionProvider",
                {"cudnn_conv_algo_search": "HEURISTIC"},
            )
        ]


def test_load_voice_cuda_without_preload_dlls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that older ONNX Runtime without preload_dlls retains the CUDA session path."""
    import onnxruntime

    monkeypatch.delattr(onnxruntime, "preload_dlls", raising=False)

    with patch("piper.voice.onnxruntime.InferenceSession") as mock_session:
        PiperVoice.load(_TEST_VOICE, use_cuda=True)
        assert mock_session.call_count == 1
        _args, kwargs = mock_session.call_args
        assert kwargs["providers"] == [
            (
                "CUDAExecutionProvider",
                {"cudnn_conv_algo_search": "HEURISTIC"},
            )
        ]


def test_load_voice_cuda_preload_exception_resilient() -> None:
    """Test that an exception during preload_dlls does not prevent session construction."""
    with (
        patch(
            "piper.voice.onnxruntime.preload_dlls",
            side_effect=RuntimeError("Preload failed"),
            create=True,
        ) as mock_preload,
        patch("piper.voice.onnxruntime.InferenceSession") as mock_session,
    ):
        voice = PiperVoice.load(_TEST_VOICE, use_cuda=True)
        assert mock_preload.call_count == 1
        assert mock_session.call_count == 1
        assert voice.session is mock_session.return_value
        _args, kwargs = mock_session.call_args
        assert kwargs["providers"] == [
            (
                "CUDAExecutionProvider",
                {"cudnn_conv_algo_search": "HEURISTIC"},
            )
        ]


def test_load_voice_cuda_disabled_no_preload() -> None:
    """Test that use_cuda=False does not call preload_dlls."""
    with (
        patch("piper.voice.onnxruntime.preload_dlls", create=True) as mock_preload,
        patch("piper.voice.onnxruntime.InferenceSession") as mock_session,
    ):
        PiperVoice.load(_TEST_VOICE, use_cuda=False)
        mock_preload.assert_not_called()
        assert mock_session.call_count == 1
        _args, kwargs = mock_session.call_args
        assert kwargs["providers"] == ["CPUExecutionProvider"]


def test_phonemize_synthesize() -> None:
    """Test phonemizing and synthesizing."""
    voice = PiperVoice.load(_TEST_VOICE)
    phonemes = voice.phonemize("Test 1. Test 2.")
    assert phonemes == [
        # Test 1.
        ["t", "ˈ", "ɛ", "s", "t", " ", "w", "ˈ", "ʌ", "n", "."],
        # Test 2.
        ["t", "ˈ", "ɛ", "s", "t", " ", "t", "ˈ", "u", "ː", "."],
    ]

    phoneme_ids = [voice.phonemes_to_ids(ps) for ps in phonemes]

    # Test 1.
    assert phoneme_ids[0] == [
        1,  # BOS
        0,
        32,
        0,  # PAD
        120,
        0,
        61,
        0,
        31,
        0,
        32,
        0,
        3,
        0,
        35,
        0,
        120,
        0,
        102,
        0,
        26,
        0,
        10,
        0,
        2,  # EOS
    ]

    # Test 2.
    assert phoneme_ids[1] == [
        1,  # BOS
        0,
        32,
        0,  # PAD
        120,
        0,
        61,
        0,
        31,
        0,
        32,
        0,
        3,
        0,
        32,
        0,
        120,
        0,
        33,
        0,
        122,
        0,
        10,
        0,
        2,  # EOS
    ]

    audio_array = voice.phoneme_ids_to_audio(phoneme_ids[0])
    assert len(audio_array) == voice.config.sample_rate  # 1 second of silence
    assert not any(audio_array)


def test_language_switch_flags_removed() -> None:
    """Test that (language) switch (flags) are removed."""
    phonemizer = EspeakPhonemizer()
    phonemes = phonemizer.phonemize("ar", "test")
    assert phonemes == [["t", "ˈ", "ɛ", "s", "t"]]


def test_synthesize() -> None:
    """Test streaming text to audio synthesis."""
    voice = PiperVoice.load(_TEST_VOICE)
    audio_chunks = list(voice.synthesize("This is a test. This is another test."))

    # One chunk per sentence
    assert len(audio_chunks) == 2
    for chunk in audio_chunks:
        sample_rate = chunk.sample_rate
        assert sample_rate == voice.config.sample_rate
        assert chunk.sample_width == 2
        assert chunk.sample_channels == 1

        # Verify 1 second of silence
        assert len(chunk.audio_float_array) == sample_rate
        assert not any(chunk.audio_float_array)

        assert len(chunk.audio_int16_array) == sample_rate
        assert not any(chunk.audio_int16_array)

        assert len(chunk.audio_int16_bytes) == sample_rate * 2
        assert not any(chunk.audio_int16_bytes)


def test_synthesize_wav() -> None:
    """Test text to audio synthesis with WAV output."""
    voice = PiperVoice.load(_TEST_VOICE)

    with io.BytesIO() as wav_io:
        wav_output: wave.Wave_write = wave.open(wav_io, "wb")
        with wav_output:
            voice.synthesize_wav("This is a test. This is another test.", wav_output)

        wav_io.seek(0)
        wav_input: wave.Wave_read = wave.open(wav_io, "rb")
        with wav_input:
            assert wav_input.getframerate() == voice.config.sample_rate
            assert wav_input.getsampwidth() == 2
            assert wav_input.getnchannels() == 1

            # Verify 2 seconds of silence (1 per sentence)
            audio_data = wav_input.readframes(wav_input.getnframes())
            assert (
                len(audio_data)
                == voice.config.sample_rate * wav_input.getsampwidth() * 2
            )
            assert not any(audio_data)


@pytest.mark.parametrize(
    "sentence_silence",
    # At 22050 Hz these all made int(rate * s * 2) odd under the old code, which
    # wrote a half frame of 16-bit PCM between sentences and misaligned the rest
    # of the stream (issue #253). 0.30 is an even control.
    [0.15, 0.25, 0.30, 0.45, 0.75],
)
def test_sentence_silence_even_byte_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sentence_silence: float
) -> None:
    """Inter-sentence silence must never leave the WAV data chunk odd-length."""
    from piper.__main__ import main

    output_path = tmp_path / "out.wav"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "piper",
            "-m",
            str(_TEST_VOICE),
            "-f",
            str(output_path),
            "--sentence-silence",
            str(sentence_silence),
        ],
    )
    # Two sentences => silence is written once, between the chunks.
    monkeypatch.setattr(sys, "stdin", io.StringIO("This is a test. This is another."))

    main()

    with wave.open(str(output_path), "rb") as wav_input:
        assert wav_input.getsampwidth() == 2
        assert wav_input.getnchannels() == 1

    # Read the on-disk `data` chunk size field directly. This is the byte the
    # bug leaves odd; wave's own reader hides it because readframes() returns
    # getnframes() * frame_size, silently dropping the trailing orphan byte.
    raw = output_path.read_bytes()
    data_idx = raw.find(b"data")
    data_size = struct.unpack("<I", raw[data_idx + 4 : data_idx + 8])[0]

    # A 16-bit mono data chunk must be a whole number of frames (even byte count).
    assert data_size % 2 == 0, f"odd data chunk ({data_size} bytes)"

    # No trailing orphan byte was written: the data chunk is exactly the two
    # one-second chunks (test voice emits 1 s of silence per sentence at 22050 Hz)
    # plus a whole number of silence samples.
    sample_rate = 22050
    silence_samples = int(sample_rate * sentence_silence)
    expected_bytes = (sample_rate * 2 * 2) + (silence_samples * 2)
    assert data_size == expected_bytes


def test_ar_tashkeel() -> None:
    """Test Arabic diacritization."""
    voice = PiperVoice.load(_TEST_VOICE)
    voice.config.espeak_voice = "ar"

    phonemes_with_diacritics = "bismˌi ʔalllˈahi ʔarrrˈaħmanˌi ʔarrrˈaħiːm"
    phonemes_without_diacritics = "bˈismillˌaːh ʔˈarɹaħmˌaːn ʔarrˈaħiːm"

    # Diacritization is enabled by default
    phonemes = voice.phonemize("بسم الله الرحمن الرحيم")
    assert phonemes_with_diacritics == "".join(phonemes[0])

    # Disable diacritization
    voice.use_tashkeel = False
    phonemes = voice.phonemize("بسم الله الرحمن الرحيم")
    assert phonemes_without_diacritics == "".join(phonemes[0])


def test_raw_phonemes() -> None:
    """Test [[ phonemes block ]]."""
    voice = PiperVoice.load(_TEST_VOICE)
    phonemes = voice.phonemize("I am the [[ bˈætmæn ]] not [[bɹˈuːs wˈe‍ɪn]]")

    # Raw phonemes should not split sentences
    assert len(phonemes) == 1

    phonemes_str = "".join("".join(ps) for ps in phonemes)
    assert phonemes_str == "aɪɐm ðə bˈætmæn nˈɑːt bɹˈuːs wˈe‍ɪn"

    # Check if entire text is just phonemes
    phonemes = voice.phonemize("[[ bˈætmæn ɪz bɹˈuːs wˈe‍ɪn ]]")
    assert len(phonemes) == 1
    phonemes_str = "".join("".join(ps) for ps in phonemes)
    assert phonemes_str == "bˈætmæn ɪz bɹˈuːs wˈe‍ɪn"


def test_synthesize_alignment() -> None:
    """Test synthesis with phoneme alignments."""
    alignments = [
        [  # Test 1.
            256,
            256,
            512,
            256,
            768,
            512,
            512,
            256,
            256,
            512,
            768,
            768,
            256,
            1280,
            1024,
            512,
            1280,
            1024,
            512,
            768,
            1536,
            512,
            768,
            768,
            768,
        ],
        [  # Test 2.
            512,
            256,
            768,
            256,
            768,
            256,
            1024,
            256,
            768,
            256,
            512,
            256,
            1024,
            512,
            512,
            256,
            1792,
            768,
            512,
            1024,
            512,
            1024,
            1280,
            2048,
            1280,
        ],
    ]

    voice = PiperVoice.load(_TEST_VOICE)
    original_phoneme_ids_to_audio = voice.phoneme_ids_to_audio
    alignments_idx = 0

    def phoneme_ids_to_audio(self, phoneme_ids, **kwargs):
        nonlocal alignments_idx
        kwargs["include_alignments"] = False
        audio = original_phoneme_ids_to_audio(self, phoneme_ids, **kwargs)
        audio_alignments = alignments[alignments_idx]
        alignments_idx += 1

        return audio, audio_alignments

    with patch.object(voice, "phoneme_ids_to_audio", phoneme_ids_to_audio):
        audio_chunks = list(voice.synthesize("Test 1. Test 2."))

    assert len(audio_chunks) == 2  # 1 chunk per sentence

    assert audio_chunks[0].phonemes == [
        "t",
        "ˈ",
        "ɛ",
        "s",
        "t",
        " ",
        "w",
        "ˈ",
        "ʌ",
        "n",
        ".",
    ]
    assert audio_chunks[0].phoneme_ids == [
        1,
        0,
        32,
        0,
        120,
        0,
        61,
        0,
        31,
        0,
        32,
        0,
        3,
        0,
        35,
        0,
        120,
        0,
        102,
        0,
        26,
        0,
        10,
        0,
        2,
    ]
    assert audio_chunks[1].phonemes == [
        "t",
        "ˈ",
        "ɛ",
        "s",
        "t",
        " ",
        "t",
        "ˈ",
        "u",
        "ː",
        ".",
    ]
    assert audio_chunks[1].phoneme_ids == [
        1,
        0,
        32,
        0,
        120,
        0,
        61,
        0,
        31,
        0,
        32,
        0,
        3,
        0,
        32,
        0,
        120,
        0,
        33,
        0,
        122,
        0,
        10,
        0,
        2,
    ]

    # Check alignments (assumes each phoneme is 1 id + pad)
    assert len(audio_chunks) == len(alignments)
    for chunk_idx, chunk in enumerate(audio_chunks):
        assert chunk.phoneme_id_samples is not None
        assert chunk.phoneme_alignments is not None

        expected_alignments = alignments[chunk_idx]
        assert len(expected_alignments) == len(chunk.phoneme_id_samples)

        phonemes = [BOS] + chunk.phonemes + [EOS]
        assert len(phonemes) == len(chunk.phoneme_alignments)
        alignment_idx = 0
        for phoneme_idx, phoneme in enumerate(phonemes):
            actual_alignment = chunk.phoneme_alignments[phoneme_idx]
            assert actual_alignment.phoneme == phoneme

            expected_samples = expected_alignments[alignment_idx]
            expected_ids = [chunk.phoneme_ids[alignment_idx]]
            alignment_idx += 1
            if phoneme != EOS:
                # PAD
                expected_samples += expected_alignments[alignment_idx]
                expected_ids.append(0)  # pad
                alignment_idx += 1

            assert actual_alignment.num_samples == expected_samples
            assert actual_alignment.phoneme_ids == expected_ids


def test_add_alignment_output_autodetect() -> None:
    """Test autodetecting and marking the Ceil tensor as an output."""
    onnx = pytest.importorskip("onnx")
    from piper.patch_voice_with_alignment import add_alignment_output

    model = onnx.parser.parse_model(
        """
        <ir_version: 8, opset_import: ["": 15]>
        agraph (float[N] input) => (float[N] output) {
            w_ceil = Ceil(input)
            output = Identity(w_ceil)
        }
        """
    )
    assert [o.name for o in model.graph.output] == ["output"]

    tensor_name = add_alignment_output(model)
    assert tensor_name == "w_ceil"
    assert [o.name for o in model.graph.output] == ["output", "w_ceil"]


def test_add_alignment_output_errors() -> None:
    """Test errors when no Ceil tensor exists or it is already an output."""
    onnx = pytest.importorskip("onnx")
    from piper.patch_voice_with_alignment import add_alignment_output

    # No Ceil node
    no_ceil = onnx.parser.parse_model(
        """
        <ir_version: 8, opset_import: ["": 15]>
        agraph (float[N] input) => (float[N] output) {
            output = Identity(input)
        }
        """
    )
    with pytest.raises(ValueError):
        add_alignment_output(no_ceil)

    # Tensor already marked as an output
    with pytest.raises(ValueError):
        add_alignment_output(no_ceil, tensor_name="output")


def test_load_include_alignments_in_memory(tmp_path: Path) -> None:
    """Test patching an unpatched model in memory at load time."""
    onnx = pytest.importorskip("onnx")
    model_path = tmp_path / "ceil_voice.onnx"
    _make_ceil_model(onnx, model_path)
    shutil.copy(_TEST_CONFIG, f"{model_path}.json")

    # Without alignments: single (unpatched) output
    voice = PiperVoice.load(model_path)
    assert [o.name for o in voice.session.get_outputs()] == ["output"]

    # With alignments: Ceil tensor is exposed as an extra output
    voice = PiperVoice.load(model_path, include_alignments=True)
    assert [o.name for o in voice.session.get_outputs()] == ["output", "w_ceil"]

    # The on-disk model is left unpatched
    on_disk = onnx.load(str(model_path))
    assert [o.name for o in on_disk.graph.output] == ["output"]


def test_load_include_alignments_no_ceil() -> None:
    """Test that loading falls back gracefully when there is no Ceil tensor."""
    # The test voice has no Ceil tensor, so alignments cannot be added.
    voice = PiperVoice.load(_TEST_VOICE, include_alignments=True)
    assert [o.name for o in voice.session.get_outputs()] == ["output"]


# -----------------------------------------------------------------------------


def _make_ceil_model(onnx, path: Path) -> None:
    """Write a minimal ONNX model with a Ceil node (unpatched, single output)."""
    helper = onnx.helper
    TensorProto = onnx.TensorProto

    inp = helper.make_tensor_value_info("input", TensorProto.FLOAT, [None])
    out = helper.make_tensor_value_info("output", TensorProto.FLOAT, [None])
    ceil_node = helper.make_node("Ceil", ["input"], ["w_ceil"])
    identity_node = helper.make_node("Identity", ["w_ceil"], ["output"])
    graph = helper.make_graph([ceil_node, identity_node], "ceil_graph", [inp], [out])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 15)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def test_phonemize_with_vowel_clusters() -> None:
    """Test phonemizing with vowel clusters."""
    voice = PiperVoice.load(_TEST_VOICE)
    voice.config.vowel_clusters = EN_US_VOWEL_CLUSTERS

    phonemes = voice.phonemize("my cow toy day no")
    assert phonemes == [
        [
            "m",
            "aɪ",
            " ",
            "k",
            "ˈ",
            "aʊ",
            " ",
            "t",
            "ˈ",
            "ɔɪ",
            " ",
            "d",
            "ˈ",
            "eɪ",
            " ",
            "n",
            "ˈ",
            "oʊ",
        ],
    ]

    phoneme_ids = [voice.phonemes_to_ids(ps) for ps in phonemes]
    assert phoneme_ids == [
        [
            1,
            0,
            25,
            0,
            161,
            0,
            3,
            0,
            23,
            0,
            120,
            0,
            162,
            0,
            3,
            0,
            32,
            0,
            120,
            0,
            163,
            0,
            3,
            0,
            17,
            0,
            120,
            0,
            164,
            0,
            3,
            0,
            26,
            0,
            120,
            0,
            165,
            0,
            2,
        ]
    ]


def test_training_phonemize_matches_inference_with_vowel_clusters() -> None:
    """Training data prep must merge vowel clusters exactly like inference does.

    Guards against the config recording clusters while the training-side
    phonemizer leaves them unmerged (which would make the trained voice emit
    diphthong ids it never saw during training).
    """
    import json

    dataset = pytest.importorskip("piper.train.vits.dataset")
    VitsDataModule = dataset.VitsDataModule

    data_module = VitsDataModule(
        csv_path="dataset.csv",
        cache_dir="cache",
        espeak_voice="en-us",
        config_path="config.json",
        voice_name="test",
        vowel_clusters=json.dumps([list(vc) for vc in EN_US_VOWEL_CLUSTERS]),
    )

    # JSON arg is parsed into the same set used at inference time.
    assert data_module.vowel_clusters == EN_US_VOWEL_CLUSTERS

    text = "my cow toy day no"
    phonemizer = EspeakPhonemizer()
    train_phonemes = phonemizer.phonemize(
        "en-us", text, vowel_clusters=data_module.vowel_clusters
    )
    infer_phonemes = phonemizer.phonemize(
        "en-us", text, vowel_clusters=EN_US_VOWEL_CLUSTERS
    )
    assert train_phonemes == infer_phonemes
