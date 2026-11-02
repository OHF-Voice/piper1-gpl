"""Tests for the command-line interface."""

import io
import json
import shutil
import sys
import wave
from pathlib import Path

import pytest

from piper.__main__ import main

_TESTS_DIR = Path(__file__).parent


@pytest.mark.parametrize("config_flag", ["-c", "--config"])
@pytest.mark.parametrize("adjacent_config", [False, True])
def test_custom_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_flag: str,
    adjacent_config: bool,
) -> None:
    """Use the requested config rather than an adjacent config, if present."""
    model_path = tmp_path / "voice.onnx"
    shutil.copy(_TESTS_DIR / "test_voice.onnx", model_path)
    config = json.loads(
        (_TESTS_DIR / "test_voice.onnx.json").read_text(encoding="utf-8")
    )
    if adjacent_config:
        (tmp_path / "voice.onnx.json").write_text(json.dumps(config), encoding="utf-8")
    config["audio"]["sample_rate"] = 16000
    config["phoneme_type"] = "text"
    config_path = tmp_path / "custom.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output_path = tmp_path / "out.wav"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "piper",
            "-m",
            str(model_path),
            config_flag,
            str(config_path),
            "-f",
            str(output_path),
        ],
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("a"))

    main()

    with wave.open(str(output_path), "rb") as wav_input:
        assert wav_input.getframerate() == 16000
        assert wav_input.getnframes() > 0
