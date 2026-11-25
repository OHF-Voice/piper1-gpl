"""Tests for preserving voice names in the HTTP API."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from piper import PiperConfig

http_server = pytest.importorskip(
    "piper.http_server", reason="Flask (the http extra) is not installed"
)


@pytest.fixture
def make_client(tmp_path: Path):
    """Start the HTTP app without loading a model or opening a socket."""

    def create(voice_names):
        config = json.loads(
            (Path(__file__).parent / "test_voice.onnx.json").read_text(encoding="utf-8")
        )
        for name in voice_names:
            (tmp_path / f"{name}.onnx").touch()
            (tmp_path / f"{name}.onnx.json").write_text(
                json.dumps(config), encoding="utf-8"
            )

        voice = Mock(config=PiperConfig.from_dict(config))
        with (
            patch(
                "sys.argv",
                [
                    "piper.http_server",
                    "--model",
                    str(tmp_path / f"{voice_names[0]}.onnx"),
                    "--data-dir",
                    str(tmp_path),
                ],
            ),
            patch.object(http_server.PiperVoice, "load", return_value=voice),
            patch.object(http_server.Flask, "run", autospec=True) as run,
        ):
            http_server.main()

        return run.call_args.args[0].test_client()

    return create


@pytest.mark.parametrize("name", ["ann", "demo", "custom.onnx", "en_US-lessac-medium"])
def test_info_preserves_voice_name(make_client, name: str) -> None:
    """Only the final model extension is removed from /info's voice name."""
    client = make_client([name])
    response = client.get("/info")
    assert response.status_code == 200
    assert response.get_json()["voice"]["name"] == name


@pytest.mark.parametrize("name", ["ann", "demo", "custom.onnx", "en_US-lessac-medium"])
def test_voices_preserves_voice_name(make_client, name: str) -> None:
    """Only the final .onnx.json extensions are removed from /voices keys."""
    client = make_client([name])
    response = client.get("/voices")
    assert response.status_code == 200
    assert set(response.get_json()) == {name}


def test_voices_does_not_collapse_distinct_names(make_client) -> None:
    """Names differing by trailing extension characters remain distinct."""
    client = make_client(["ann", "a"])
    response = client.get("/voices")
    assert response.status_code == 200
    assert set(response.get_json()) == {"ann", "a"}
