"""Tests for the streaming HTTP client."""

import threading
import time
from typing import Iterator, List

import pytest

from piper.chunking import PROFILES, ChunkingConfig
from piper.client import (
    ClientConfig,
    PiperClient,
    PlayerConfig,
    rate_to_length_scale,
    sd_volume_to_multiplier,
    wav_header,
)

from .stub_server import BYTES_PER_WORD, FR_SAMPLE_RATE, SAMPLE_RATE, StubServer


@pytest.fixture(name="server")
def server_fixture() -> Iterator[StubServer]:
    with StubServer() as server:
        yield server


def make_client(server: StubServer, **kwargs) -> PiperClient:
    config = ClientConfig(url=server.url, **kwargs)
    return PiperClient(config)


# -----------------------------------------------------------------------------
# Parameter mapping
# -----------------------------------------------------------------------------


def test_rate_to_length_scale() -> None:
    assert rate_to_length_scale(0) == pytest.approx(1.0)
    assert rate_to_length_scale(100, rate_factor=3.0) == pytest.approx(1 / 3)
    assert rate_to_length_scale(-100, rate_factor=3.0) == pytest.approx(3.0)
    # Out of range values are clamped, never rejected
    assert rate_to_length_scale(1000, rate_factor=2.0) == pytest.approx(0.5)


def test_rate_scales_a_custom_base() -> None:
    assert rate_to_length_scale(0, base_length_scale=0.8) == pytest.approx(0.8)


def test_sd_volume_to_multiplier() -> None:
    # speech-dispatcher's nominal volume is 100
    assert sd_volume_to_multiplier(100) == pytest.approx(1.0)
    assert sd_volume_to_multiplier(0) == pytest.approx(0.5)
    assert sd_volume_to_multiplier(-100) == pytest.approx(0.25)


# -----------------------------------------------------------------------------
# Server info
# -----------------------------------------------------------------------------


def test_info_and_sample_rate(server: StubServer) -> None:
    client = make_client(server)
    assert client.info()["voice"]["name"] == "en_US-test-medium"
    assert client.sample_rate() == SAMPLE_RATE


def test_voices(server: StubServer) -> None:
    client = make_client(server)
    assert "fr_FR-test-medium" in client.voices()


def test_sample_rate_follows_the_voice(server: StubServer) -> None:
    """Not every voice is 22.05 kHz: the wrong rate slows speech down."""
    client = make_client(server, voice="fr_FR-test-medium")
    assert client.sample_rate() == FR_SAMPLE_RATE
    assert client.sample_rate("en_US-test-medium") == SAMPLE_RATE

    # Unknown voices fall back to the server's default
    assert client.sample_rate("xx_XX-unknown-medium") == SAMPLE_RATE


def test_url_without_scheme(server: StubServer) -> None:
    client = PiperClient(ClientConfig(url=server.url.replace("http://", "")))
    assert client.sample_rate() == SAMPLE_RATE


# -----------------------------------------------------------------------------
# Chunking and streaming
# -----------------------------------------------------------------------------


def test_client_chunks_text_into_several_requests(server: StubServer) -> None:
    client = make_client(
        server, chunking=ChunkingConfig(max_words=3, first_max_words=2, min_words=1)
    )
    audio = b"".join(client.stream("one two three four five six seven eight nine"))

    assert server.chunk_texts() == [
        "one two",
        "three four five",
        "six seven eight",
        "nine",
    ]
    assert len(audio) == 9 * BYTES_PER_WORD


def test_chunks_of_one_utterance_share_a_group(server: StubServer) -> None:
    """Otherwise the server would preempt the chunks of the same utterance."""
    client = make_client(server, chunking=ChunkingConfig(max_words=2, min_words=1))
    list(client.stream("one two three four"))

    groups = server.groups()
    assert len(groups) > 1
    assert len(set(groups)) == 1
    assert all(request["preempt"] for request in server.requests)


def test_different_utterances_use_different_groups(server: StubServer) -> None:
    client = make_client(server)
    list(client.stream("first utterance."))
    list(client.stream("second utterance."))
    assert len(set(server.groups())) == 2


def test_server_chunk_mode_sends_one_request(server: StubServer) -> None:
    client = make_client(server, chunk_mode="server")
    text = "one two three four five six seven eight"
    list(client.stream(text))

    assert server.texts() == [text]
    assert server.requests[0]["chunk"]["enabled"] is True


def test_client_chunk_mode_disables_server_chunking(server: StubServer) -> None:
    client = make_client(server)
    list(client.stream("one two three four five six"))
    assert all(request["chunk"] == {"enabled": False} for request in server.requests)


def test_iter_audio_reports_the_chunk_of_each_piece(server: StubServer) -> None:
    """Audio must be attributable to a piece of text (for index marks)."""
    client = make_client(
        server, chunking=ChunkingConfig(max_words=2, first_max_words=2, min_words=1)
    )
    text = "alpha beta gamma delta"
    pieces = list(client.iter_audio(text))

    assert pieces
    for chunk, audio_bytes in pieces:
        assert audio_bytes
        assert text[chunk.start : chunk.end] == chunk.text

    assert [chunk.text for chunk, _ in pieces][0] == "alpha beta"
    assert pieces[-1][0].is_last


def test_synthesis_parameters_are_sent(server: StubServer) -> None:
    client = make_client(
        server,
        voice="fr_FR-test-medium",
        length_scale=0.75,
        volume=0.5,
        sentence_silence=0.1,
        chunking=PROFILES["off"],
    )
    list(client.stream("bonjour."))

    request = server.requests[0]
    assert request["voice"] == "fr_FR-test-medium"
    assert request["length_scale"] == 0.75
    assert request["volume"] == 0.5
    assert request["sentence_silence"] == 0.1


def test_chunk_silence_is_inserted_between_chunks(server: StubServer) -> None:
    """Silence between chunks hides boundary artifacts."""
    config = ChunkingConfig(max_words=2, first_max_words=2, min_words=1)
    client = make_client(server, chunking=config, chunk_silence=0.1)
    audio = b"".join(client.stream("one two three four"))

    silence_bytes = int(SAMPLE_RATE * 0.1) * 2
    assert len(audio) == (4 * BYTES_PER_WORD) + silence_bytes


def test_wav_header_is_written_for_an_unknown_length(server: StubServer) -> None:
    """--output wav writes a header players accept before the length is known."""
    header = wav_header(FR_SAMPLE_RATE)

    assert len(header) == 44
    assert header[:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
    assert int.from_bytes(header[24:28], "little") == FR_SAMPLE_RATE
    # Length fields are "big enough", not zero: players stop at end of stream
    data_size = int.from_bytes(header[40:44], "little")
    assert data_size > 0
    assert int.from_bytes(header[4:8], "little") == data_size + 36


def test_empty_text_sends_nothing(server: StubServer) -> None:
    client = make_client(server)
    assert not list(client.stream("   "))
    assert not server.requests


def test_prefetch_keeps_the_engine_busy() -> None:
    """With prefetch, the next chunk is requested before the current one ends."""
    with StubServer(chunk_delay=0.05) as server:
        client = make_client(
            server,
            chunking=ChunkingConfig(max_words=2, first_max_words=2, min_words=1),
            prefetch=2,
        )
        stream = client.iter_audio("one two three four five six")
        next(stream)  # first piece of audio of the first chunk
        time.sleep(0.2)

        # More than one chunk has been requested while we were "playing"
        assert len(server.requests) > 1
        stream.close()


# -----------------------------------------------------------------------------
# Interruption
# -----------------------------------------------------------------------------


def test_stop_ends_iteration_and_notifies_the_server() -> None:
    with StubServer(chunk_delay=0.02) as server:
        client = make_client(server, chunking=PROFILES["off"])
        received: List[bytes] = []

        def consume() -> None:
            for audio_bytes in client.stream(" ".join(["word"] * 200)):
                received.append(audio_bytes)

        thread = threading.Thread(target=consume)
        thread.start()
        time.sleep(0.2)

        client.stop()
        thread.join(timeout=10)

        assert not thread.is_alive()
        assert client.stopped
        assert server.stops, "server was not told to stop"
        # Far less than the 200 words of audio
        assert sum(len(data) for data in received) < 200 * BYTES_PER_WORD


def test_stop_before_speaking_is_cleared_by_reset(server: StubServer) -> None:
    client = make_client(server)
    client.stop(notify_server=False)
    assert client.stopped

    client.reset()
    assert not client.stopped
    assert list(client.stream("hello."))


def test_speak_writes_to_a_sink(server: StubServer) -> None:
    class Sink:
        def __init__(self) -> None:
            self.data = bytearray()
            self.drained = False
            self.stopped = False

        def write(self, audio_bytes: bytes) -> None:
            self.data.extend(audio_bytes)

        def drain(self, timeout=None) -> None:
            self.drained = True

        def stop(self) -> None:
            self.stopped = True

    client = make_client(server)
    sink = Sink()
    assert client.speak("one two three.", sink) is True
    assert len(sink.data) == 3 * BYTES_PER_WORD
    assert sink.drained
    assert not sink.stopped


# -----------------------------------------------------------------------------
# Player configuration
# -----------------------------------------------------------------------------


def test_player_template_substitution() -> None:
    config = PlayerConfig(
        command="myplayer --rate={rate} --channels={channels} --lat={latency_ms}",
        latency_ms=25,
    )
    assert config.resolve(16000, 1) == [
        "myplayer",
        "--rate=16000",
        "--channels=1",
        "--lat=25",
    ]


def test_player_auto_detection_uses_a_known_player() -> None:
    config = PlayerConfig()
    if not PlayerConfig.is_available():
        pytest.skip("no audio player installed")

    command = config.resolve(SAMPLE_RATE)
    assert command[0] in [executable for executable, _ in config.templates]
    assert str(SAMPLE_RATE) in " ".join(command)


def test_player_auto_detection_without_player() -> None:
    config = PlayerConfig(templates=(("definitely-not-a-player", "nope -"),))
    with pytest.raises(RuntimeError):
        config.resolve(SAMPLE_RATE)
