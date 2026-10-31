"""Tests for the HTTP API."""

import io
import json
import sys
import wave
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

_TESTS_DIR = Path(__file__).parent


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

    from piper.http_server import main

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
            "piper.http_server",
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
