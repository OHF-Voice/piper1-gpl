"""Minimal stand-in for piper.http_server, used by client/module tests.

Synthesis is replaced by silence whose length is proportional to the text, so
tests stay fast and do not need a voice model.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

SAMPLE_RATE = 22050
FR_SAMPLE_RATE = 44100
"""Voices do not all share a sample rate: the French stub voice uses another
one, like fr_FR-tom-medium does."""

BYTES_PER_WORD = 2205 * 2  # 100 ms of 16-bit audio per word

VOICES = {
    "en_US-test-medium": {
        "audio": {"sample_rate": SAMPLE_RATE},
        "espeak": {"voice": "en-us"},
        "language": {"code": "en_US"},
    },
    "fr_FR-test-medium": {
        "audio": {"sample_rate": FR_SAMPLE_RATE},
        "espeak": {"voice": "fr"},
        "language": {"code": "fr_FR"},
    },
}


def voice_sample_rate(voice: Optional[str]) -> int:
    """Sample rate of a voice, as the real server reports it."""
    config = VOICES.get(voice or "")
    if not config:
        return SAMPLE_RATE

    return int(config["audio"]["sample_rate"])


class StubServer:
    """A stub Piper HTTP server that records the requests it receives."""

    def __init__(self, chunk_delay: float = 0.0, port: int = 0) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.stops: List[Dict[str, Any]] = []
        self.chunk_delay = chunk_delay
        """Seconds of "synthesis time" per audio chunk sent."""

        self.lock = threading.Lock()
        self.cancelled: Dict[str, bool] = {}
        self.shutdown_requested = threading.Event()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def _body(self) -> Dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                data: Dict[str, Any] = {}
                query = urlsplit(self.path).query
                if query:
                    data.update(
                        {key: values[0] for key, values in parse_qs(query).items()}
                    )

                if length:
                    raw = self.rfile.read(length)
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            data.update(parsed)
                    except ValueError:
                        data["text"] = raw.decode("utf-8")

                return data

            def _json(self, payload: Any) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if path == "/info":
                    self._json(
                        {
                            "voice": {
                                "name": "en_US-test-medium",
                                "language": "en-us",
                                "num_speakers": 1,
                                "sample_rate": SAMPLE_RATE,
                                "sample_width": 2,
                                "num_channels": 1,
                            },
                            "loaded_voices": sorted(VOICES),
                            "streams": [],
                            "last": None,
                        }
                    )
                elif path == "/voices":
                    self._json(VOICES)
                else:
                    self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                data = self._body()

                if path == "/shutdown":
                    # Only used by the tests, to stop a stub started as a
                    # standalone process (see main()).
                    self._json({"stopping": True})
                    stub.shutdown_requested.set()
                    threading.Thread(target=stub.stop, daemon=True).start()
                    return

                if path == "/stop":
                    with stub.lock:
                        stub.stops.append(data)
                        for key in list(stub.cancelled):
                            stub.cancelled[key] = True

                    self._json({"stopped": [], "num_stopped": 0})
                    return

                if path not in ("/stream", "/synthesize", "/"):
                    self.send_error(404)
                    return

                text = str(data.get("text", ""))
                with stub.lock:
                    stub.requests.append(data)
                    stream_id = str(data.get("stream_id", ""))
                    stub.cancelled[stream_id] = False

                num_bytes = max(1, len(text.split())) * BYTES_PER_WORD
                sample_rate = voice_sample_rate(data.get("voice"))
                self.send_response(200)
                self.send_header("Content-Type", "audio/L16")
                self.send_header("X-Piper-Sample-Rate", str(sample_rate))
                self.send_header("X-Piper-Stream-Id", stream_id)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                sent = 0
                block = 4410 * 2
                try:
                    while sent < num_bytes:
                        with stub.lock:
                            if stub.cancelled.get(stream_id):
                                break

                        if stub.chunk_delay:
                            time.sleep(stub.chunk_delay)

                        size = min(block, num_bytes - sent)
                        self.wfile.write(b"%x\r\n" % size)
                        self.wfile.write(bytes(size))
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                        sent += size

                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "StubServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def texts(self) -> List[str]:
        """Texts of the requests received, in arrival order."""
        with self.lock:
            return [str(request.get("text", "")) for request in self.requests]

    def chunk_texts(self) -> List[str]:
        """Texts of the requests received, in chunk order.

        Chunks of one utterance are requested concurrently (the client
        synthesizes ahead of playback), so arrival order is not chunk order.
        The chunk index is the suffix of ``stream_id`` ("<group>-<index>").
        """

        def index(request: Dict[str, Any]) -> int:
            suffix = str(request.get("stream_id", "")).rpartition("-")[2]
            return int(suffix) if suffix.isdigit() else 0

        with self.lock:
            requests = sorted(self.requests, key=index)

        return [str(request.get("text", "")) for request in requests]

    def groups(self) -> List[Optional[str]]:
        with self.lock:
            return [request.get("group") for request in self.requests]

    def __enter__(self) -> "StubServer":
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()


def main() -> None:
    """Run the stub as a standalone server (used to test autostart).

    Unknown options (``--model``, ``--host``, ...) are ignored so that the stub
    can stand in for ``python3 -m piper.http_server``.
    """
    import argparse  # pylint: disable=import-outside-toplevel

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--startup-delay", type=float, default=0.0)
    parser.add_argument("--lifetime", type=float, default=120.0)
    args, _unknown = parser.parse_known_args()

    time.sleep(args.startup_delay)
    server = StubServer(port=args.port).start()
    # Never outlive the test run, even if the test forgets to stop it.
    server.shutdown_requested.wait(args.lifetime)


if __name__ == "__main__":
    main()
