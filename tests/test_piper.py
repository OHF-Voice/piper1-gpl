"""Tests for Piper."""

import io
import shutil
import wave
from pathlib import Path
from unittest.mock import patch

import onnx
import pytest
from onnx import TensorProto, helper

from piper import PiperVoice
from piper.const import BOS, EOS
from piper.phonemize_espeak import EspeakPhonemizer

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
    model_path = tmp_path / "ceil_voice.onnx"
    _make_ceil_model(model_path)
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


def _make_ceil_model(path: Path) -> None:
    """Write a minimal ONNX model with a Ceil node (unpatched, single output)."""

    inp = helper.make_tensor_value_info("input", TensorProto.FLOAT, [None])
    out = helper.make_tensor_value_info("output", TensorProto.FLOAT, [None])
    ceil_node = helper.make_node("Ceil", ["input"], ["w_ceil"])
    identity_node = helper.make_node("Identity", ["w_ceil"], ["output"])
    graph = helper.make_graph([ceil_node, identity_node], "ceil_graph", [inp], [out])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 15)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
