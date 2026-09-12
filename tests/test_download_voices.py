"""Tests for downloading voice files."""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import ContentTooShortError

import pytest

from piper import download_voices

_VOICE = "en_US-lessac-medium"
_PAYLOADS = {".onnx": b"complete model data", ".onnx.json": b'{"audio": {}}'}


@pytest.fixture(name="voice_server")
def fixture_voice_server(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[set[str], list[str]]]:
    """Serve voice files, optionally closing before Content-Length is reached."""
    short_responses: set[str] = set()
    requests: list[str] = []

    class VoiceRequestHandler(BaseHTTPRequestHandler):
        """Serve complete or truncated responses over a real HTTP connection."""

        def do_GET(self) -> None:
            """Send the requested file."""
            extension = self.path.removeprefix("/")
            requests.append(extension)
            payload = _PAYLOADS[extension]
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if extension in short_responses:
                payload = payload[: len(payload) // 2]
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", 0), VoiceRequestHandler) as server:
        monkeypatch.setattr(
            download_voices,
            "URL_FORMAT",
            f"http://127.0.0.1:{server.server_port}/{{extension}}",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield short_responses, requests
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("extension", _PAYLOADS)
@pytest.mark.parametrize("force_redownload", [False, True])
def test_short_download_preserves_voice_and_allows_retry(
    tmp_path: Path,
    voice_server: tuple[set[str], list[str]],
    extension: str,
    force_redownload: bool,
) -> None:
    """A short model or config download must not publish either partial file."""
    short_responses, _ = voice_server
    original_files = {}
    if force_redownload:
        for suffix in _PAYLOADS:
            filename = f"{_VOICE}{suffix}"
            original_files[filename] = b"original " + suffix.encode()
            (tmp_path / filename).write_bytes(original_files[filename])

    short_responses.add(extension)
    with pytest.raises(ContentTooShortError):
        download_voices.download_voice(_VOICE, tmp_path, force_redownload)

    assert {
        path.name: path.read_bytes() for path in tmp_path.iterdir()
    } == original_files

    short_responses.clear()
    download_voices.download_voice(_VOICE, tmp_path, force_redownload)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == {
        f"{_VOICE}{suffix}": payload for suffix, payload in _PAYLOADS.items()
    }


@pytest.mark.parametrize("extension", _PAYLOADS)
@pytest.mark.parametrize("existing_data", [b"", b"cached file"])
def test_download_only_missing_or_empty_files(
    tmp_path: Path,
    voice_server: tuple[set[str], list[str]],
    extension: str,
    existing_data: bytes,
) -> None:
    """Preserve nonempty cached files and download missing or empty files."""
    _, requests = voice_server
    (tmp_path / f"{_VOICE}{extension}").write_bytes(existing_data)

    download_voices.download_voice(_VOICE, tmp_path)

    assert requests == [
        suffix for suffix in _PAYLOADS if suffix != extension or not existing_data
    ]
    for suffix, payload in _PAYLOADS.items():
        expected = existing_data if suffix == extension and existing_data else payload
        assert (tmp_path / f"{_VOICE}{suffix}").read_bytes() == expected
    assert len(list(tmp_path.iterdir())) == 2


def test_download_skips_cached_voice(
    tmp_path: Path, voice_server: tuple[set[str], list[str]]
) -> None:
    """An already downloaded voice does not require another HTTP request."""
    _, requests = voice_server
    for extension, payload in _PAYLOADS.items():
        (tmp_path / f"{_VOICE}{extension}").write_bytes(payload)

    download_voices.download_voice(_VOICE, tmp_path)

    assert not requests
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == {
        f"{_VOICE}{suffix}": payload for suffix, payload in _PAYLOADS.items()
    }
