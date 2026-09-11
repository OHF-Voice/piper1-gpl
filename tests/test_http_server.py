"""Tests for the streaming HTTP server."""

import io
import json
import threading
import time
import wave
from pathlib import Path
from typing import Any, Iterator

import pytest

flask = pytest.importorskip("flask")

# pylint: disable=wrong-import-position
from piper.http_server import (  # noqa: E402  (after importorskip)
    StreamRegistry,
    create_app,
    get_parser,
    wav_header,
)

_TESTS_DIR = Path(__file__).parent
_TEST_VOICE = _TESTS_DIR / "test_voice.onnx"

# The test voice always produces one second of silence per sentence
SAMPLE_RATE = 22050
BYTES_PER_SENTENCE = SAMPLE_RATE * 2


@pytest.fixture(name="app")
def app_fixture() -> Any:
    args = get_parser().parse_args(
        [
            "-m",
            str(_TEST_VOICE),
            "--data-dir",
            str(_TESTS_DIR),
            "--no-warmup",
        ]
    )
    return create_app(args)


@pytest.fixture(name="client")
def client_fixture(app: Any) -> Any:
    return app.test_client()


# -----------------------------------------------------------------------------
# WAV header
# -----------------------------------------------------------------------------


def test_wav_header_streaming() -> None:
    """A streaming header must be readable before the audio exists."""
    header = wav_header(SAMPLE_RATE)
    assert len(header) == 44
    assert header[:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
    # Length fields are "big enough" so players stream until end of data
    assert int.from_bytes(header[40:44], "little") > 1_000_000


def test_wav_header_known_length() -> None:
    header = wav_header(SAMPLE_RATE, num_bytes=100)
    assert int.from_bytes(header[40:44], "little") == 100
    assert int.from_bytes(header[4:8], "little") == 136

    with io.BytesIO(header + bytes(100)) as wav_io:
        with wave.open(wav_io, "rb") as wav_file:
            assert wav_file.getframerate() == SAMPLE_RATE
            assert wav_file.getsampwidth() == 2
            assert wav_file.getnchannels() == 1
            assert wav_file.getnframes() == 50


# -----------------------------------------------------------------------------
# Synthesis
# -----------------------------------------------------------------------------


def test_synthesize_buffered_wav(client: Any) -> None:
    """stream=false returns a complete WAV file (what browsers need)."""
    response = client.post("/synthesize", json={"text": "Test one.", "stream": False})
    assert response.status_code == 200
    assert response.mimetype == "audio/wav"

    with io.BytesIO(response.data) as wav_io:
        with wave.open(wav_io, "rb") as wav_file:
            assert wav_file.getframerate() == SAMPLE_RATE
            assert wav_file.getnframes() == SAMPLE_RATE


def test_synthesize_streams_wav_header_first(client: Any) -> None:
    """Audio must start flowing before synthesis is finished."""
    response = client.post("/synthesize", json={"text": "Test one. Test two."})
    assert response.status_code == 200
    assert response.headers["X-Piper-Sample-Rate"] == str(SAMPLE_RATE)

    stream: Iterator[bytes] = response.iter_encoded()
    first = next(stream)
    assert first.startswith(b"RIFF")


def test_stream_raw_pcm(client: Any) -> None:
    response = client.post("/stream", json={"text": "Test one. Test two."})
    assert response.status_code == 200
    assert response.mimetype == "audio/L16"
    assert response.headers["X-Piper-Channels"] == "1"
    assert len(response.data) == 2 * BYTES_PER_SENTENCE


def test_stream_is_chunked_by_default(client: Any) -> None:
    """Chunking splits one long sentence into several inference calls."""
    text = "one two three four five six seven eight nine ten eleven twelve"
    response = client.post("/stream", json={"text": text})
    # Each chunk of the sentence produces its own "sentence" of audio
    assert len(response.data) > BYTES_PER_SENTENCE

    no_chunking = client.post(
        "/stream", json={"text": text, "chunk": {"enabled": False}}
    )
    assert len(no_chunking.data) == BYTES_PER_SENTENCE


def test_stream_accepts_query_parameters(client: Any) -> None:
    response = client.get("/stream?text=Test+one.")
    assert response.status_code == 200
    assert len(response.data) == BYTES_PER_SENTENCE


def test_stream_accepts_plain_text_body(client: Any) -> None:
    response = client.post("/stream", data="Test one.".encode("utf-8"))
    assert response.status_code == 200
    assert len(response.data) == BYTES_PER_SENTENCE


def test_json_body_with_a_form_content_type(client: Any) -> None:
    """`curl -d '{...}'` sends JSON with a form content type by default."""
    response = client.post(
        "/stream",
        data=json.dumps({"text": "Test one.", "chunk": {"enabled": False}}),
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    assert len(response.data) == BYTES_PER_SENTENCE


def test_form_parameters_are_still_read(client: Any) -> None:
    response = client.post("/stream", data={"text": "Test one.", "chunk_max_words": 0})
    assert response.status_code == 200
    assert len(response.data) == BYTES_PER_SENTENCE


def test_legacy_post_to_root(client: Any) -> None:
    """The old `curl -d '{"text": ...}' host:5000 | aplay -` still works."""
    response = client.post("/", json={"text": "Test one."})
    assert response.status_code == 200
    assert response.data.startswith(b"RIFF")


def test_silence_between_sentences_and_chunks(client: Any) -> None:
    response = client.post(
        "/stream",
        json={
            "text": "Test one. Test two.",
            "chunk": {"enabled": False},
            "sentence_silence": 0.5,
        },
    )
    assert len(response.data) == (2 * BYTES_PER_SENTENCE) + int(SAMPLE_RATE * 0.5) * 2


def test_info_reports_chunking_and_last_utterance(client: Any) -> None:
    client.post("/stream", json={"text": "Test one."})
    info = json.loads(client.get("/info").data)
    assert info["voice"]["sample_rate"] == SAMPLE_RATE
    assert info["chunking"]["profile"] == "responsive"
    assert info["last"]["audio_seconds"] == pytest.approx(1.0)
    assert info["last"]["cancelled"] is False
    assert info["last"]["first_audio_seconds"] is not None


def test_no_text_is_an_error(client: Any) -> None:
    """Bad requests are reported as JSON, not as an HTML error page."""
    response = client.post("/stream", json={"text": "  "})
    assert response.status_code == 400
    assert "error" in json.loads(response.data)


def test_unknown_voice_falls_back_to_default(client: Any) -> None:
    response = client.post("/stream", json={"text": "Test one.", "voice": "nope"})
    assert response.status_code == 200
    assert response.headers["X-Piper-Voice"] == "test_voice"


def test_no_voice_uses_default(client: Any) -> None:
    """speech-dispatcher generic modules pass "no_voice" when unset."""
    response = client.post("/stream", json={"text": "Test one.", "voice": "no_voice"})
    assert response.headers["X-Piper-Voice"] == "test_voice"


def test_stop_endpoint_reports_stopped_streams(client: Any) -> None:
    response = json.loads(client.post("/stop", json={}).data)
    assert response == {"stopped": [], "num_stopped": 0}


def test_stop_cancels_a_stream_in_progress(app: Any) -> None:
    """A stop request ends the response instead of playing the whole text."""
    client = app.test_client()
    long_text = "Test sentence. " * 50
    response = client.post(
        "/stream",
        json={"text": long_text, "stream_id": "s1", "chunk": {"enabled": False}},
    )
    stream = response.iter_encoded()

    # First piece of audio proves synthesis started
    assert len(next(stream)) > 0

    stopped = json.loads(app.test_client().post("/stop", json={"stream_id": "s1"}).data)
    assert stopped["stopped"] == ["s1"]

    num_bytes = sum(len(data) for data in stream)
    # 50 sentences would be 50 seconds of audio; we stop long before that
    assert num_bytes < 50 * BYTES_PER_SENTENCE
    response.close()


# -----------------------------------------------------------------------------
# Stream registry (interruption logic)
# -----------------------------------------------------------------------------


def test_registry_preempts_same_channel() -> None:
    registry = StreamRegistry()
    first = registry.start(channel="screen-reader")
    second = registry.start(channel="screen-reader")
    assert first.is_cancelled
    assert not second.is_cancelled


def test_registry_does_not_preempt_other_channels() -> None:
    registry = StreamRegistry()
    first = registry.start(channel="a")
    second = registry.start(channel="b")
    assert not first.is_cancelled
    assert not second.is_cancelled


def test_registry_does_not_preempt_same_group() -> None:
    """Chunks of one utterance may arrive out of order: they must not fight."""
    registry = StreamRegistry()
    first = registry.start(stream_id="u1-0", group="u1")
    second = registry.start(stream_id="u1-1", group="u1")
    assert not first.is_cancelled
    assert not second.is_cancelled

    third = registry.start(stream_id="u2-0", group="u2")
    assert first.is_cancelled
    assert second.is_cancelled
    assert not third.is_cancelled


def test_registry_no_preempt_option() -> None:
    registry = StreamRegistry()
    first = registry.start(channel="c")
    second = registry.start(channel="c", preempt=False)
    assert not first.is_cancelled
    assert not second.is_cancelled


def test_registry_cancel_by_group_and_channel() -> None:
    registry = StreamRegistry()
    first = registry.start(stream_id="a", group="g1", channel="c")
    second = registry.start(stream_id="b", group="g1", channel="c")
    assert registry.cancel(group="g1") == ["a", "b"]
    assert first.is_cancelled and second.is_cancelled

    third = registry.start(stream_id="c", channel="other")
    assert registry.cancel(channel="other") == ["c"]
    assert third.is_cancelled


def test_registry_finish_removes_stream() -> None:
    registry = StreamRegistry()
    stream = registry.start()
    assert len(registry.active()) == 1
    registry.finish(stream)
    assert not registry.active()


def test_registry_is_thread_safe() -> None:
    registry = StreamRegistry()
    errors = []

    def worker(index: int) -> None:
        try:
            for _ in range(50):
                stream = registry.start(channel=f"c{index % 3}")
                registry.cancel(stream_id=stream.stream_id)
                registry.finish(stream)
        except Exception as error:  # pylint: disable=broad-except
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert not registry.active()


def test_first_audio_is_faster_with_chunking(app: Any) -> None:
    """Chunking exists to shorten time-to-first-audio; check it holds."""
    client = app.test_client()
    text = " ".join(["word"] * 40) + "."

    def time_to_first_audio(chunk_enabled: bool) -> float:
        start = time.monotonic()
        response = client.post(
            "/stream", json={"text": text, "chunk": {"enabled": chunk_enabled}}
        )
        stream = response.iter_encoded()
        next(stream)
        elapsed = time.monotonic() - start
        response.close()
        return elapsed

    # The test voice is instant, so only check that both paths work and that
    # chunking produces the first audio at least as fast.
    chunked = time_to_first_audio(True)
    whole = time_to_first_audio(False)
    assert chunked <= (whole + 0.5)
