"""Tests for downloading voices."""

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set
from unittest.mock import patch
from urllib.error import ContentTooShortError, HTTPError

import pytest

from piper import download_voices

_VOICES_JSON = {
    "de_DE-karlsson-low": {"aliases": ["de-karlsson-low"]},
    "en_US-lessac-medium": {"aliases": []},
    "ja_JP-hi_fi_captain-medium": {"aliases": ["ja_JA-hi_fi_captain-medium"]},
}


class FakeResponse(io.BytesIO):
    """Response body with the headers that urlopen's responses have."""

    def __init__(self, data: bytes) -> None:
        """Serve `data` with a matching Content-Length."""
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class FakeUrlopen:
    """Stand-in for urlopen that serves a fixed set of URLs."""

    def __init__(self, available: Optional[Dict[str, bytes]] = None) -> None:
        """Serve voices.json plus any URL substrings in `available`."""
        self.available = available or {}
        self.requested: list = []

    def __call__(self, url: str):
        """Return a file-like object for the URL, or raise a 404."""
        self.requested.append(url)

        if url == download_voices.VOICES_JSON:
            return FakeResponse(json.dumps(_VOICES_JSON).encode("utf-8"))

        for url_part, data in self.available.items():
            if url_part in url:
                return FakeResponse(data)

        raise HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def clear_voices_cache():
    """Keep the voices.json cache from leaking between tests."""
    download_voices._VOICES_DICT = None  # pylint: disable=protected-access
    yield
    download_voices._VOICES_DICT = None  # pylint: disable=protected-access


def test_download_current_name(tmp_path: Path) -> None:
    """Test that a current voice name downloads without consulting voices.json."""
    fake = FakeUrlopen({"en_US-lessac-medium": b"fake"})
    with patch.object(download_voices, "urlopen", fake):
        name = download_voices.download_voice("en_US-lessac-medium", tmp_path)

    assert name == "en_US-lessac-medium"

    assert (tmp_path / "en_US-lessac-medium.onnx").read_bytes() == b"fake"
    assert (tmp_path / "en_US-lessac-medium.onnx.json").read_bytes() == b"fake"

    # voices.json is only fetched when a name has to be resolved
    assert download_voices.VOICES_JSON not in fake.requested
    assert "en/en_US/lessac/medium/en_US-lessac-medium.onnx" in fake.requested[0]


def test_download_legacy_name(tmp_path: Path) -> None:
    """Test that a pre-1.0 name is resolved through its alias."""
    fake = FakeUrlopen({"de_DE-karlsson-low": b"fake"})
    with patch.object(download_voices, "urlopen", fake):
        name = download_voices.download_voice("de-karlsson-low", tmp_path)

    assert name == "de_DE-karlsson-low"

    # Files are saved under the current name
    assert (tmp_path / "de_DE-karlsson-low.onnx").exists()
    assert not (tmp_path / "de-karlsson-low.onnx").exists()


def test_download_renamed_voice(tmp_path: Path) -> None:
    """Test that a renamed voice whose old name still parses is resolved."""
    # ja_JA-hi_fi_captain-medium matches VOICE_PATTERN, so it is tried directly
    # first and only resolved after the download 404s.
    fake = FakeUrlopen({"ja_JP-hi_fi_captain-medium": b"fake"})
    with patch.object(download_voices, "urlopen", fake):
        name = download_voices.download_voice("ja_JA-hi_fi_captain-medium", tmp_path)

    assert name == "ja_JP-hi_fi_captain-medium"

    assert (tmp_path / "ja_JP-hi_fi_captain-medium.onnx").exists()
    assert not (tmp_path / "ja_JA-hi_fi_captain-medium.onnx").exists()

    # The old path was tried before voices.json was consulted
    assert "ja/ja_JA/" in fake.requested[0]
    assert download_voices.VOICES_JSON in fake.requested


def test_unknown_name(tmp_path: Path) -> None:
    """Test that an unparseable name with no alias is still an error."""
    fake = FakeUrlopen()
    with patch.object(download_voices, "urlopen", fake):
        with pytest.raises(ValueError):
            download_voices.download_voice("not-a-voice", tmp_path)


def test_missing_voice(tmp_path: Path) -> None:
    """Test that a parseable name with no alias reports the download failure."""
    fake = FakeUrlopen()
    with patch.object(download_voices, "urlopen", fake):
        with pytest.raises(HTTPError):
            download_voices.download_voice("en_US-nonexistent-medium", tmp_path)

    assert not list(tmp_path.iterdir())


# -----------------------------------------------------------------------------
# Interrupted downloads, served over a real HTTP connection since urlopen's own
# handling of a dropped connection is what's under test.

_VOICE = "en_US-lessac-medium"
_PAYLOADS = {".onnx": b"complete model data", ".onnx.json": b'{"audio": {}}'}


class VoiceServer:
    """Records requests and which file extensions to cut short."""

    def __init__(self) -> None:
        """Start with every response complete."""
        self.short_extensions: Set[str] = set()
        self.requested: List[str] = []


@pytest.fixture(name="voice_server")
def fixture_voice_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[VoiceServer]:
    """Serve voice files, closing early for extensions in short_extensions."""
    voice_server = VoiceServer()

    class VoiceRequestHandler(BaseHTTPRequestHandler):
        """Serve complete or truncated voice files."""

        def do_GET(self) -> None:  # pylint: disable=invalid-name
            """Send the requested file."""
            extension = self.path.lstrip("/")
            voice_server.requested.append(extension)
            payload = _PAYLOADS[extension]
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if extension in voice_server.short_extensions:
                payload = payload[: len(payload) // 2]
            self.wfile.write(payload)

        def log_message(self, *args) -> None:  # pylint: disable=arguments-differ
            """Keep request logs out of test output."""

    with ThreadingHTTPServer(("127.0.0.1", 0), VoiceRequestHandler) as server:
        monkeypatch.setattr(
            download_voices,
            "URL_FORMAT",
            f"http://127.0.0.1:{server.server_port}/{{extension}}",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield voice_server
        finally:
            server.shutdown()
            thread.join()


def _dir_contents(path: Path) -> Dict[str, bytes]:
    """Return the name and contents of every entry in a directory."""
    return {p.name: p.read_bytes() for p in path.iterdir()}


@pytest.mark.parametrize("short_extension", _PAYLOADS)
@pytest.mark.parametrize("force_redownload", [False, True])
def test_interrupted_download(
    tmp_path: Path,
    voice_server: VoiceServer,
    short_extension: str,
    force_redownload: bool,
) -> None:
    """Test that a truncated download leaves no partial files behind."""
    original_files: Dict[str, bytes] = {}
    if force_redownload:
        # A working voice must survive a failed redownload
        for extension in _PAYLOADS:
            name = f"{_VOICE}{extension}"
            original_files[name] = b"original " + extension.encode()
            (tmp_path / name).write_bytes(original_files[name])

    voice_server.short_extensions.add(short_extension)
    with pytest.raises(ContentTooShortError):
        download_voices.download_voice(_VOICE, tmp_path, force_redownload)

    assert _dir_contents(tmp_path) == original_files

    # Retrying after the failure downloads the complete voice
    voice_server.short_extensions.clear()
    download_voices.download_voice(_VOICE, tmp_path, force_redownload)
    assert _dir_contents(tmp_path) == {
        f"{_VOICE}{extension}": payload for extension, payload in _PAYLOADS.items()
    }


@pytest.mark.parametrize("existing_extension", _PAYLOADS)
@pytest.mark.parametrize("existing_data", [b"", b"cached file"])
def test_download_missing_or_empty(
    tmp_path: Path,
    voice_server: VoiceServer,
    existing_extension: str,
    existing_data: bytes,
) -> None:
    """Test that only missing or empty files are downloaded."""
    (tmp_path / f"{_VOICE}{existing_extension}").write_bytes(existing_data)

    download_voices.download_voice(_VOICE, tmp_path)

    is_cached = bool(existing_data)
    assert voice_server.requested == [
        extension
        for extension in _PAYLOADS
        if (extension != existing_extension) or (not is_cached)
    ]
    assert _dir_contents(tmp_path) == {
        f"{_VOICE}{extension}": (
            existing_data
            if is_cached and (extension == existing_extension)
            else payload
        )
        for extension, payload in _PAYLOADS.items()
    }


def test_download_cached_voice(tmp_path: Path, voice_server: VoiceServer) -> None:
    """Test that a fully downloaded voice is not requested again."""
    for extension, payload in _PAYLOADS.items():
        (tmp_path / f"{_VOICE}{extension}").write_bytes(payload)

    download_voices.download_voice(_VOICE, tmp_path)

    assert not voice_server.requested
