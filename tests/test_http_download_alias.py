"""Tests for selecting a downloaded voice by the HTTP response's name."""

import io
import json
import wave
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import numpy as np
import pytest

from piper import PiperConfig, PiperVoice, download_voices
from piper.voice import AudioChunk

http_server = pytest.importorskip("piper.http_server", reason="Flask is not installed")


class DownloadResponse(io.BytesIO):
    """An in-memory download with a valid Content-Length."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


@pytest.mark.parametrize(
    ("requested", "canonical"),
    [
        ("de-karlsson-low", "de_DE-karlsson-low"),
        ("ja_JA-hi_fi_captain-medium", "ja_JP-hi_fi_captain-medium"),
        ("en_US-lessac-medium", "en_US-lessac-medium"),
    ],
)
def test_download_response_selects_the_downloaded_voice(
    tmp_path: Path, requested: str, canonical: str
) -> None:
    """Using the returned name must not silently synthesize the default voice."""
    config_data = json.loads(
        (Path(__file__).parent / "test_voice.onnx.json").read_text(encoding="utf-8")
    )
    config = PiperConfig.from_dict(config_data)
    model = tmp_path / "en_US-default-medium.onnx"
    model.touch()
    default_voice = Mock(spec=PiperVoice, config=config)
    downloaded_voice = Mock(spec=PiperVoice, config=config)
    for voice, sample in ((default_voice, 0.25), (downloaded_voice, 0.5)):
        voice.synthesize.return_value = [
            AudioChunk(
                sample_rate=22050,
                sample_width=2,
                sample_channels=1,
                audio_float_array=np.array([sample], dtype=np.float32),
                phonemes=[],
                phoneme_ids=[],
            )
        ]

    def load_voice(path: Path, **_kwargs) -> Mock:
        return downloaded_voice if Path(path).stem == canonical else default_voice

    def urlopen(url: str) -> DownloadResponse:
        if url == download_voices.VOICES_JSON:
            return DownloadResponse(
                json.dumps({canonical: {"aliases": [requested]}}).encode("utf-8")
            )
        if f"/{canonical}.onnx.json" in url:
            return DownloadResponse(json.dumps(config_data).encode("utf-8"))
        if f"/{canonical}.onnx" in url:
            return DownloadResponse(b"downloaded model")
        raise HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    with (
        patch(
            "sys.argv",
            [
                "piper.http_server",
                "--model",
                str(model),
                "--data-dir",
                str(tmp_path),
                "--download-dir",
                str(tmp_path),
            ],
        ),
        patch.object(http_server.PiperVoice, "load", side_effect=load_voice),
        patch.object(http_server.Flask, "run", autospec=True) as run,
        patch.object(download_voices, "urlopen", side_effect=urlopen),
        patch.object(download_voices, "_VOICES_DICT", None),
    ):
        http_server.main()
        client = run.call_args.args[0].test_client()
        download = client.post("/download", json={"voice": requested})
        assert download.status_code == 200
        returned_name = download.get_data(as_text=True)
        audio = client.post(
            "/synthesize", json={"text": "Hello", "voice": returned_name}
        )

    assert audio.status_code == 200
    with wave.open(io.BytesIO(audio.data), "rb") as wav:
        assert wav.readframes(1) == np.array([16383], dtype=np.int16).tobytes()
    assert returned_name == canonical
    assert (tmp_path / f"{returned_name}.onnx").is_file()
