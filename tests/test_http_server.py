"""Tests for the HTTP synthesis server."""

import io
import json
import struct
import sys
import wave
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

http_server = pytest.importorskip(
    "piper_tts.http_server", reason="Flask (the http extra) is not installed"
)

_TESTS_DIR = Path(__file__).parent
_TEST_VOICE = _TESTS_DIR / "test_voice.onnx"


@pytest.mark.parametrize("sentence_count", [2, 3])
@pytest.mark.parametrize("sentence_silence", [0.0, 0.25, 0.30])
def test_sentence_silence(
    monkeypatch: pytest.MonkeyPatch,
    sentence_count: int,
    sentence_silence: float,
) -> None:
    """Silence must contain whole int16 samples between every sentence."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "piper_tts.http_server",
            "--model",
            str(_TEST_VOICE),
            "--sentence-silence",
            str(sentence_silence),
        ],
    )
    # Capture the app without starting a network listener.
    with patch.object(http_server.Flask, "run", autospec=True) as run:
        http_server.main()

    app = run.call_args.args[0]
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.post(
            "/synthesize", json={"text": "This is a test. " * sentence_count}
        )
    assert response.status_code == 200

    # Inspect the data chunk directly: wave.readframes(getnframes()) hides an
    # orphan byte when the header advertises a partial frame (issue #253).
    raw = response.data
    data_offset = raw.index(b"data") + 4
    data_size = struct.unpack_from("<I", raw, data_offset)[0]
    pcm = raw[data_offset + 4 : data_offset + 4 + data_size]
    assert len(pcm) == data_size

    with wave.open(io.BytesIO(raw), "rb") as wav_input:
        sample_rate = wav_input.getframerate()
        assert sample_rate == 22050
        assert wav_input.getsampwidth() == 2
        assert wav_input.getnchannels() == 1
        frame_size = wav_input.getsampwidth() * wav_input.getnchannels()
        assert data_size % frame_size == 0, f"partial PCM frame ({data_size} bytes)"

        # The test voice emits one second of zeros per sentence.
        sentence_bytes = sample_rate * frame_size
        silence_samples = int(sample_rate * sentence_silence)
        silence_bytes = silence_samples * frame_size
        expected_bytes = (
            sentence_count * sentence_bytes + (sentence_count - 1) * silence_bytes
        )
        assert data_size == expected_bytes
        assert wav_input.getnframes() == expected_bytes // frame_size
        assert wav_input.readframes(wav_input.getnframes()) == pcm

    for gap in range(sentence_count - 1):
        start = (gap + 1) * sentence_bytes + gap * silence_bytes
        silence = pcm[start : start + silence_bytes]
        assert len(silence) // frame_size == silence_samples
        assert silence == bytes(silence_bytes)


@pytest.mark.parametrize("voice_name", [None, "alternate"])
@pytest.mark.parametrize("prepatched", [False, True])
def test_voice_alignments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    voice_name: Optional[str],
    prepatched: bool,
) -> None:
    """Return alignments for both default and lazily loaded voices."""
    pytest.importorskip("flask")
    onnx = pytest.importorskip("onnx")
    from flask import Flask

    from piper_tts.http_server import main

    # Add a duration tensor to the silence-generating test voice. One text
    # phoneme produces five ids: BOS, PAD, 'a', PAD, EOS.
    model = onnx.load(str(_TESTS_DIR / "test_voice.onnx"))
    model.graph.initializer.append(
        onnx.helper.make_tensor("durations", onnx.TensorProto.FLOAT, [5], [1.0] * 5)
    )
    model.graph.node.append(onnx.helper.make_node("Ceil", ["durations"], ["w_ceil"]))
    if prepatched:
        model.graph.output.append(
            onnx.helper.make_tensor_value_info("w_ceil", onnx.TensorProto.FLOAT, [5])
        )

    config = json.loads(
        (_TESTS_DIR / "test_voice.onnx.json").read_text(encoding="utf-8")
    )
    config["phoneme_type"] = "text"
    for name in ("default", "alternate"):
        onnx.save(model, str(tmp_path / f"{name}.onnx"))
        (tmp_path / f"{name}.onnx.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "piper_tts.http_server",
            "-m",
            str(tmp_path / "default.onnx"),
            "--data-dir",
            str(tmp_path),
        ],
    )
    with patch.object(Flask, "run", autospec=True) as run:
        main()
    client = run.call_args.args[0].test_client()
    data = {"text": "a"}
    if voice_name is not None:
        data["voice"] = voice_name

    # A second request also exercises the loaded-voice cache.
    for _ in range(2):
        response = client.post("/synthesize", json=data)
        assert response.status_code == 200
        with wave.open(io.BytesIO(response.data), "rb") as wav_input:
            assert wav_input.getnframes() == 22050

        info = client.get("/info").get_json()
        assert info["last"]["alignments"] == [
            {"phoneme": "^", "seconds": pytest.approx(512 / 22050)},
            {"phoneme": "a", "seconds": pytest.approx(512 / 22050)},
            {"phoneme": "$", "seconds": pytest.approx(256 / 22050)},
        ]
