"""Streaming HTTP client for the Piper web server.

This is the piece that makes ``piper.http_server`` usable as a screen reader
backend. It is intentionally dependency-free (standard library only) so that it
starts fast, and every behaviour is configurable:

* **Chunking**: long texts are split into small pieces on word/punctuation/
  sentence boundaries before being sent (see :mod:`piper.chunking`), so audio
  starts playing after the first few words instead of after the whole text.
* **Pipelining**: while a chunk is playing, the next one is already being
  synthesized.
* **Interruption**: :meth:`PiperClient.stop` kills playback, aborts the HTTP
  streams and tells the server to abandon the inference in progress. It is safe
  to call from a signal handler or another thread.
* **Playback**: raw PCM is piped into a player process (pw-play, paplay, aplay,
  ffplay, or any command you configure), or written to a file/stdout for use in
  a shell pipeline.

Command line usage (reads text from stdin or from the arguments)::

    piper-client "Hello world."
    echo "Hello world." | piper-client --voice en_US-kristin-medium
    piper-client --output raw "Hello world." | aplay -r 22050 -f S16_LE -t raw -

See docs/SPEECHD.md for the speech-dispatcher configuration.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import logging
import os
import queue
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .chunking import ChunkingConfig, TextChunk, iter_chunks

_LOGGER = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:5000"

# speech-dispatcher sends rate/pitch/volume in [-100, 100]
SD_MIN = -100
SD_MAX = 100

#: rate=+100 makes speech RATE_FACTOR times faster, rate=-100 that much slower
DEFAULT_RATE_FACTOR = 3.0

__all__ = [
    "AudioSink",
    "ClientConfig",
    "PiperClient",
    "PlayerConfig",
    "rate_to_length_scale",
    "sd_volume_to_multiplier",
    "wav_header",
    "main",
]

# Length fields of a WAV file that is still being written. Players that stream
# from a pipe accept a "big enough" length and stop at end of stream.
_STREAMING_WAV_SIZE = 0x7FFFFFFF - 128


def wav_header(sample_rate: int, sample_width: int = 2, num_channels: int = 1) -> bytes:
    """Build a 44-byte WAV header for a stream of unknown length.

    ``piper.http_server`` has the same helper for its streaming responses, but
    it is not imported here on purpose: this module stays standard-library only
    (importing the server would pull in flask) and usable against a remote
    server.
    """
    with io.BytesIO() as wav_io:
        wav_file: wave.Wave_write = wave.open(wav_io, "wb")
        with wav_file:
            wav_file.setframerate(sample_rate)
            wav_file.setsampwidth(sample_width)
            wav_file.setnchannels(num_channels)
            wav_file.writeframes(b"")

        header = bytearray(wav_io.getvalue()[:44])

    # RIFF size and data size
    header[4:8] = (_STREAMING_WAV_SIZE + 36).to_bytes(4, "little")
    header[40:44] = _STREAMING_WAV_SIZE.to_bytes(4, "little")
    return bytes(header)


# -----------------------------------------------------------------------------
# Parameter mapping (speech-dispatcher units -> Piper synthesis parameters)
# -----------------------------------------------------------------------------


def rate_to_length_scale(
    rate: float,
    base_length_scale: float = 1.0,
    rate_factor: float = DEFAULT_RATE_FACTOR,
) -> float:
    """Convert a speech-dispatcher rate in [-100, 100] to a length scale.

    ``rate=0`` keeps ``base_length_scale``, ``rate=100`` divides it by
    ``rate_factor`` (faster), ``rate=-100`` multiplies it (slower).
    """
    rate = max(SD_MIN, min(SD_MAX, rate))
    return base_length_scale * (rate_factor ** (-rate / 100.0))


def sd_volume_to_multiplier(volume: float) -> float:
    """Convert a speech-dispatcher volume in [-100, 100] to an audio multiplier.

    speech-dispatcher's nominal volume is 100 (full), so 100 maps to 1.0 and
    every 100 points below that halves the amplitude.
    """
    volume = max(SD_MIN, min(SD_MAX, volume))
    return 2.0 ** ((volume - 100.0) / 100.0)


# -----------------------------------------------------------------------------
# Playback
# -----------------------------------------------------------------------------


@dataclass
class PlayerConfig:
    """How raw PCM is played.

    ``command`` is a shell-style command template. ``{rate}``, ``{channels}``,
    ``{width}`` and ``{latency_ms}`` are substituted. The player must read raw
    PCM from stdin. ``auto`` picks the first available player.
    """

    command: str = "auto"
    latency_ms: int = 40
    """Target playback buffer. Lower = interruption is heard sooner, but risk of
    underruns (drop-outs) increases."""

    #: Player templates, in order of preference.
    templates: Sequence[Tuple[str, str]] = (
        (
            "pw-play",
            "pw-play --raw --format=s16 --rate={rate} --channels={channels}"
            " --latency={latency_ms}ms -",
        ),
        (
            "paplay",
            "paplay --raw --format=s16le --rate={rate} --channels={channels}"
            " --latency-msec={latency_ms} --client-name=piper",
        ),
        (
            "aplay",
            "aplay -q -t raw -f S16_LE -r {rate} -c {channels}"
            " --buffer-time={buffer_us} -",
        ),
        (
            "ffplay",
            "ffplay -hide_banner -loglevel quiet -nodisp -autoexit -f s16le"
            " -ar {rate} -ch_layout mono -",
        ),
    )

    def resolve(self, rate: int, channels: int = 1, width: int = 2) -> List[str]:
        """Return the player command as an argv list."""
        command = self.command
        if command in ("auto", "", None):
            for executable, template in self.templates:
                if shutil.which(executable):
                    command = template
                    break
            else:
                raise RuntimeError(
                    "No audio player found. Install pipewire (pw-play), "
                    "pulseaudio-utils (paplay), alsa-utils (aplay) or ffmpeg "
                    "(ffplay), or set --player."
                )

        command = command.format(
            rate=rate,
            channels=channels,
            width=width,
            latency_ms=self.latency_ms,
            buffer_us=self.latency_ms * 1000,
        )
        return shlex.split(command)

    @staticmethod
    def is_available() -> bool:
        return any(
            shutil.which(executable) for executable, _ in PlayerConfig().templates
        )


class AudioSink:
    """Plays raw PCM through a player subprocess, and can be killed instantly.

    A fresh player process is started for each utterance and killed on
    :meth:`stop`, which is the only reliable way to drop audio that is already
    buffered in the sound server.
    """

    def __init__(
        self, config: PlayerConfig, sample_rate: int, num_channels: int = 1
    ) -> None:
        self.config = config
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None

    def write(self, audio_bytes: bytes) -> None:
        """Write PCM to the player, starting it on first use."""
        if not audio_bytes:
            return

        with self._lock:
            proc = self._proc
            if (proc is None) or (proc.poll() is not None):
                command = self.config.resolve(self.sample_rate, self.num_channels)
                _LOGGER.debug("Starting player: %s", command)
                # pylint: disable=consider-using-with
                proc = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._proc = proc

        assert proc.stdin is not None
        try:
            proc.stdin.write(audio_bytes)
            proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            # Player was killed (stop) or died
            _LOGGER.debug("Player is gone, dropping %d bytes", len(audio_bytes))

    def drain(self, timeout: Optional[float] = None) -> None:
        """Wait for buffered audio to finish playing."""
        with self._lock:
            proc, self._proc = self._proc, None

        if proc is None:
            return

        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except (BrokenPipeError, ValueError):
            pass

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _LOGGER.warning("Player did not exit, killing it")
            proc.kill()

    def stop(self) -> None:
        """Kill the player immediately, dropping buffered audio."""
        with self._lock:
            proc, self._proc = self._proc, None

        if proc is None:
            return

        _LOGGER.debug("Killing player")
        try:
            proc.kill()
        except OSError:
            pass

        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

        # Reap without blocking playback of the next utterance
        threading.Thread(target=proc.wait, daemon=True).start()


class FileSink:
    """Writes raw PCM to a binary stream (a file, or stdout in a pipeline)."""

    def __init__(self, output_file: Any) -> None:
        self._file = output_file

    def write(self, audio_bytes: bytes) -> None:
        self._file.write(audio_bytes)
        self._file.flush()

    def drain(self, timeout: Optional[float] = None) -> None:
        try:
            self._file.flush()
        except (BrokenPipeError, ValueError):
            pass

    def stop(self) -> None:
        self.drain()


# -----------------------------------------------------------------------------
# Client
# -----------------------------------------------------------------------------


@dataclass
class ClientConfig:
    """Everything the client needs to talk to the server."""

    url: str = DEFAULT_URL
    voice: Optional[str] = None
    speaker: Optional[str] = None
    speaker_id: Optional[int] = None
    #
    length_scale: Optional[float] = None
    noise_scale: Optional[float] = None
    noise_w_scale: Optional[float] = None
    volume: Optional[float] = None
    normalize_audio: Optional[bool] = None
    """None means: let the server decide (it disables normalization when the
    text is chunked, because normalizing every chunk separately makes the
    loudness jump)."""

    sentence_silence: Optional[float] = None
    chunk_silence: Optional[float] = None
    #
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    chunk_mode: str = "client"
    """``client`` (one request per chunk, default) or ``server`` (send the whole
    text and let the server chunk it)."""

    prefetch: int = 1
    """Number of chunks synthesized ahead of playback (0 = strictly serial)."""

    channel: str = "default"
    """Preemption group on the server: a new utterance in the same channel
    cancels the previous one."""

    preempt: bool = True
    timeout: float = 30.0
    """Socket timeout in seconds for a single chunk request."""

    def synthesis_params(self) -> Dict[str, Any]:
        """Synthesis parameters to send with every request."""
        params: Dict[str, Any] = {}
        for name in (
            "voice",
            "speaker",
            "speaker_id",
            "length_scale",
            "noise_scale",
            "noise_w_scale",
            "volume",
            "normalize_audio",
            "sentence_silence",
            "chunk_silence",
        ):
            value = getattr(self, name)
            if value is not None:
                params[name] = value

        return params


class PiperClient:
    """Streaming client for the Piper HTTP server."""

    def __init__(self, config: Optional[ClientConfig] = None) -> None:
        self.config = config or ClientConfig()
        split = urlsplit(
            self.config.url if "://" in self.config.url else f"http://{self.config.url}"
        )
        self._host = split.hostname or "localhost"
        self._port = split.port or (443 if split.scheme == "https" else 80)
        self._https = split.scheme == "https"
        self._base_path = split.path.rstrip("/")

        self._stop_event = threading.Event()
        self._connections_lock = threading.Lock()
        self._connections: List[http.client.HTTPConnection] = []
        self._sample_rate: Optional[int] = None
        self._voice_sample_rates: Dict[str, int] = {}

    # -- server info ------------------------------------------------------

    def _connect(self) -> http.client.HTTPConnection:
        if self._https:
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                self._host, self._port, timeout=self.config.timeout
            )
        else:
            connection = http.client.HTTPConnection(
                self._host, self._port, timeout=self.config.timeout
            )

        with self._connections_lock:
            self._connections.append(connection)

        return connection

    def _close(self, connection: http.client.HTTPConnection) -> None:
        with self._connections_lock:
            if connection in self._connections:
                self._connections.remove(connection)

        try:
            connection.close()
        except OSError:
            pass

    def _request(
        self, path: str, body: Optional[Dict[str, Any]] = None, method: str = "POST"
    ) -> Tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
        connection = self._connect()
        data = json.dumps(body or {}).encode("utf-8")
        connection.request(
            method,
            f"{self._base_path}{path}",
            body=data,
            headers={"Content-Type": "application/json", "Accept": "audio/pcm"},
        )
        response = connection.getresponse()
        if response.status != 200:
            error = response.read().decode("utf-8", errors="replace")
            self._close(connection)
            raise RuntimeError(f"{path} failed with {response.status}: {error[:500]}")

        return connection, response

    def info(self) -> Dict[str, Any]:
        """Get server info (voice, sample rate, chunking defaults)."""
        connection, response = self._request("/info", method="GET")
        try:
            return json.loads(response.read().decode("utf-8"))
        finally:
            self._close(connection)

    def voices(self) -> Dict[str, Any]:
        """Get the voices available on the server."""
        connection, response = self._request("/voices", method="GET")
        try:
            return json.loads(response.read().decode("utf-8"))
        finally:
            self._close(connection)

    def sample_rate(self, voice: Optional[str] = None) -> int:
        """Sample rate of ``voice``, or of the configured one (cached).

        Voices do not all share a sample rate (22.05 kHz and 44.1 kHz are both
        common), and audio played at the wrong rate is slowed down or sped up.
        The rate of the *requested* voice is therefore used, not the rate of
        the server's default voice.
        """
        name = voice or self.config.voice
        if name:
            rate = self._voice_sample_rates.get(name)
            if rate is None:
                rate = self._lookup_sample_rate(name)

            if rate:
                return rate

        if self._sample_rate is None:
            self._sample_rate = int(self.info()["voice"]["sample_rate"])

        return self._sample_rate

    def _lookup_sample_rate(self, voice: str) -> Optional[int]:
        """Ask the server for the sample rate of one voice."""
        try:
            voice_config = self.voices().get(voice) or {}
            rate = int(voice_config.get("audio", {}).get("sample_rate", 0))
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as error:
            _LOGGER.debug("Cannot get the sample rate of %s: %s", voice, error)
            return None

        if rate > 0:
            self._voice_sample_rates[voice] = rate
            return rate

        return None

    def _note_sample_rate(
        self, voice: Optional[str], sample_rate: Optional[str]
    ) -> None:
        """Remember the sample rate a response reported (it is authoritative)."""
        if not sample_rate:
            return

        try:
            rate = int(sample_rate)
        except ValueError:
            return

        if rate <= 0:
            return

        if voice:
            self._voice_sample_rates[voice] = rate
        elif self._sample_rate is None:
            self._sample_rate = rate

    # -- synthesis --------------------------------------------------------

    def iter_audio(
        self, text: str, group: Optional[str] = None, read_size: int = 4096
    ) -> Iterator[Tuple[TextChunk, bytes]]:
        """Yield ``(chunk, audio_bytes)`` for ``text`` as it is synthesized.

        Text is chunked client-side (unless ``chunk_mode="server"``) and chunks
        are requested ahead of time so that playback never has to wait for the
        network. Knowing which chunk each piece of audio belongs to is what
        makes progress reporting (index marks) possible.

        Iteration stops as soon as :meth:`stop` is called. All requests of one
        call share a ``group`` so they never preempt each other.
        """
        self._stop_event.clear()

        if self.config.chunk_mode == "server":
            text = text.strip()
            chunks = (
                [TextChunk(text=text, start=0, end=len(text), index=0, is_last=True)]
                if text
                else []
            )
        else:
            chunks = list(iter_chunks(text, self.config.chunking))

        if not chunks:
            return

        pipeline = _ChunkPipeline(
            client=self,
            chunks=chunks,
            group=group or uuid.uuid4().hex,
            read_size=read_size,
            prefetch=max(0, int(self.config.prefetch)),
        )
        # Optional silence between chunks: a cheap way to hide artifacts at
        # chunk boundaries without giving up small chunks.
        silence = b""
        if self.config.chunk_silence and (len(chunks) > 1):
            silence = bytes(int(self.sample_rate() * self.config.chunk_silence) * 2)

        previous: Optional[TextChunk] = None
        try:
            for chunk, audio_bytes in pipeline:
                if self._stop_event.is_set():
                    break

                if silence and (previous is not None) and (chunk is not previous):
                    yield chunk, silence

                previous = chunk
                yield chunk, audio_bytes
        finally:
            pipeline.close()

    def stream(
        self, text: str, group: Optional[str] = None, read_size: int = 4096
    ) -> Iterator[bytes]:
        """Yield raw PCM for ``text`` as it is synthesized."""
        for _chunk, audio_bytes in self.iter_audio(
            text, group=group, read_size=read_size
        ):
            yield audio_bytes

    def speak(self, text: str, sink: Any, drain: bool = True) -> bool:
        """Synthesize ``text`` and write the audio to ``sink``.

        :return: True if the whole text was spoken, False if interrupted.
        """
        completed = True
        for audio_bytes in self.stream(text):
            if self._stop_event.is_set():
                completed = False
                break

            sink.write(audio_bytes)

        if self._stop_event.is_set():
            completed = False
            sink.stop()
        elif drain:
            sink.drain()

        return completed

    # -- interruption -----------------------------------------------------

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def stop(self, notify_server: bool = True) -> None:
        """Interrupt everything, immediately.

        Safe to call from a signal handler or another thread: it only closes
        sockets and sets a flag. The server is told to abandon the inference in
        progress so the next utterance is not queued behind it.
        """
        self._stop_event.set()

        with self._connections_lock:
            connections = list(self._connections)
            self._connections.clear()

        for connection in connections:
            try:
                connection.close()
            except OSError:
                pass

        if not notify_server:
            return

        # Best effort, on a separate connection with a short timeout: never let
        # stopping block on the network.
        try:
            connection = (  # pylint: disable=consider-using-with
                http.client.HTTPSConnection(self._host, self._port, timeout=1.0)
                if self._https
                else http.client.HTTPConnection(self._host, self._port, timeout=1.0)
            )
            body = json.dumps({"channel": self.config.channel}).encode("utf-8")
            connection.request(
                "POST",
                f"{self._base_path}/stop",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            connection.getresponse().read()
            connection.close()
        except OSError as error:
            _LOGGER.debug("Failed to notify server of stop: %s", error)

    def reset(self) -> None:
        """Clear the stop flag before speaking again."""
        self._stop_event.clear()

    # -- internal ---------------------------------------------------------

    @property
    def normalize_audio(self) -> Optional[bool]:
        return self.config.normalize_audio

    @property
    def chunking(self) -> ChunkingConfig:
        return self.config.chunking

    def _chunk_request_body(self, text: str, group: str, index: int) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "text": text,
            "stream_id": f"{group}-{index}",
            # Chunks of one utterance share a group, so they preempt whatever
            # was playing before but never each other (requests can arrive out
            # of order).
            "group": group,
            "channel": self.config.channel,
            "preempt": self.config.preempt,
        }
        body.update(self.config.synthesis_params())

        if self.config.chunk_mode == "server":
            body["chunk"] = {
                "enabled": self.config.chunking.enabled,
                "max_words": self.config.chunking.max_words,
                "first_max_words": self.config.chunking.first_max_words,
                "min_words": self.config.chunking.min_words,
                "max_chars": self.config.chunking.max_chars,
            }
        else:
            # Already chunked here: don't split again on the server. The server
            # can no longer see that the text was chunked, so normalization has
            # to be turned off explicitly to keep the loudness stable.
            body["chunk"] = {"enabled": False}
            if (self.normalize_audio is None) and self.chunking.enabled:
                body["normalize_audio"] = False

        return body


class _ChunkPipeline:
    """Requests chunks ahead of time and yields their audio in order.

    This is an implementation detail of :class:`PiperClient` and uses its
    internals on purpose.
    """

    # pylint: disable=protected-access

    def __init__(
        self,
        client: PiperClient,
        chunks: Sequence[TextChunk],
        group: str,
        read_size: int = 4096,
        prefetch: int = 1,
    ) -> None:
        self._client = client
        self._chunks = chunks
        self._group = group
        self._read_size = read_size
        self._closed = threading.Event()
        # Number of chunks that may be in flight at the same time
        self._slots = threading.Semaphore(max(1, prefetch + 1))
        self._queues: "queue.Queue[Any]" = queue.Queue()
        self._threads: List[threading.Thread] = []
        self._error: Optional[BaseException] = None

        self._producer = threading.Thread(target=self._produce, daemon=True)
        self._producer.start()

    def _produce(self) -> None:
        for chunk in self._chunks:
            if self._closed.is_set() or self._client.stopped:
                break

            self._slots.acquire()  # pylint: disable=consider-using-with
            if self._closed.is_set() or self._client.stopped:
                self._slots.release()
                break

            chunk_queue: "queue.Queue[Any]" = queue.Queue(maxsize=64)
            self._queues.put((chunk, chunk_queue))
            thread = threading.Thread(
                target=self._fetch, args=(chunk, chunk_queue), daemon=True
            )
            self._threads.append(thread)
            thread.start()

        self._queues.put(None)  # type: ignore[arg-type]

    def _fetch(self, chunk: TextChunk, chunk_queue: "queue.Queue[Any]") -> None:
        connection = None
        try:
            body = self._client._chunk_request_body(
                chunk.text, self._group, chunk.index
            )
            connection, response = self._client._request("/stream", body)
            # The response says which sample rate the audio really has.
            self._client._note_sample_rate(
                self._client.config.voice, response.getheader("X-Piper-Sample-Rate")
            )
            while not (self._closed.is_set() or self._client.stopped):
                data = response.read(self._read_size)
                if not data:
                    break

                chunk_queue.put(data)
        except BaseException as error:  # pylint: disable=broad-except
            if not (self._closed.is_set() or self._client.stopped):
                chunk_queue.put(error)
        finally:
            if connection is not None:
                self._client._close(connection)

            chunk_queue.put(None)
            self._slots.release()

    def __iter__(self) -> Iterator[Tuple[TextChunk, bytes]]:
        while True:
            item = self._queues.get()
            if item is None:
                return

            chunk, chunk_queue = item
            while True:
                data = chunk_queue.get()
                if data is None:
                    break

                if isinstance(data, BaseException):
                    raise data

                yield chunk, data

    def close(self) -> None:
        self._closed.set()
        # Unblock the producer if it is waiting for a slot
        for _ in range(len(self._chunks) + 1):
            self._slots.release()


# -----------------------------------------------------------------------------
# Command line
# -----------------------------------------------------------------------------


def _env(*names: str, default: Optional[str] = None) -> Optional[str]:
    """First non-empty environment variable among ``names``."""
    for name in names:
        value = os.environ.get(name)
        if value:
            value = value.strip()
            # speech-dispatcher generic modules pass this when the client did
            # not ask for a specific voice
            if value and (value != "no_voice"):
                return value

    return default


def _env_float(*names: str, default: Optional[float] = None) -> Optional[float]:
    value = _env(*names)
    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        _LOGGER.warning("Invalid number in environment: %s", value)
        return default


def normalize_voice_name(voice: Optional[str]) -> Optional[str]:
    """Clean up a voice name coming from speech-dispatcher.

    Generic modules pass ``no_voice`` when the client did not select a voice,
    and voices are sometimes configured with their file name.
    """
    if not voice:
        return None

    voice = voice.strip()
    if voice in ("no_voice", "NULL", "none", "default"):
        return None

    for suffix in (".onnx.json", ".onnx"):
        if voice.endswith(suffix):
            return voice[: -len(suffix)]

    return voice


def add_client_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the options shared by the CLI and the speech-dispatcher module."""
    parser.add_argument(
        "--url",
        default=_env("PIPER_URL", default=DEFAULT_URL),
        help=f"Base URL of the Piper HTTP server (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--voice",
        default=_env("PIPER_VOICE", "VOICE"),
        help="Voice name, e.g. en_US-kristin-medium ($VOICE)",
    )
    parser.add_argument("--speaker", help="Speaker name for multi-speaker voices")
    parser.add_argument("--speaker-id", type=int, help="Speaker id")
    #
    parser.add_argument(
        "--rate",
        type=float,
        default=_env_float("PIPER_RATE", "RATE"),
        help="Speech rate in speech-dispatcher units [-100, 100] ($RATE)",
    )
    parser.add_argument(
        "--rate-factor",
        type=float,
        default=_env_float("PIPER_RATE_FACTOR", default=DEFAULT_RATE_FACTOR),
        help="How much faster/slower rate=+/-100 is (default: %(default)s)",
    )
    parser.add_argument(
        "--length-scale",
        type=float,
        default=_env_float("PIPER_LENGTH_SCALE"),
        help="Phoneme length (overrides --rate; < 1 is faster)",
    )
    parser.add_argument("--noise-scale", type=float, help="Generator noise")
    parser.add_argument("--noise-w-scale", type=float, help="Phoneme width noise")
    parser.add_argument(
        "--sd-volume",
        type=float,
        default=_env_float("PIPER_VOLUME", "VOLUME"),
        help="Volume in speech-dispatcher units [-100, 100] ($VOLUME)",
    )
    parser.add_argument(
        "--volume", type=float, help="Audio multiplier (overrides --sd-volume)"
    )
    parser.add_argument(
        "--normalize",
        dest="normalize_audio",
        action="store_true",
        default=None,
        help="Scale each chunk to the full volume range (may cause loudness jumps)",
    )
    parser.add_argument(
        "--no-normalize",
        dest="normalize_audio",
        action="store_false",
        default=None,
        help="Never normalize audio",
    )
    parser.add_argument(
        "--sentence-silence",
        type=float,
        default=_env_float("PIPER_SENTENCE_SILENCE"),
        help="Seconds of silence after each sentence",
    )
    parser.add_argument(
        "--chunk-silence",
        type=float,
        default=_env_float("PIPER_CHUNK_SILENCE"),
        help="Seconds of silence between chunks (hides boundary artifacts)",
    )
    #
    # Chunking
    parser.add_argument(
        "--chunk-profile",
        default=_env("PIPER_CHUNK_PROFILE"),
        help="Chunking preset: instant, responsive, balanced, smooth, off",
    )
    parser.add_argument(
        "--chunk-max-words",
        type=int,
        default=_env_float("PIPER_CHUNK_MAX_WORDS"),
        help="Maximum words per chunk sent to the server",
    )
    parser.add_argument(
        "--chunk-first-max-words",
        type=int,
        default=_env_float("PIPER_CHUNK_FIRST_MAX_WORDS"),
        help="Maximum words in the first chunk (lower = faster first audio)",
    )
    parser.add_argument(
        "--chunk-min-words",
        type=int,
        default=_env_float("PIPER_CHUNK_MIN_WORDS"),
        help="Minimum words before breaking at a clause boundary",
    )
    parser.add_argument(
        "--chunk-max-chars",
        type=int,
        default=_env_float("PIPER_CHUNK_MAX_CHARS"),
        help="Hard limit on chunk length in characters",
    )
    parser.add_argument(
        "--chunk-mode",
        choices=("client", "server"),
        default=_env("PIPER_CHUNK_MODE", default="client"),
        help="Chunk here (default) or let the server do it",
    )
    parser.add_argument(
        "--prefetch",
        type=int,
        default=int(_env_float("PIPER_PREFETCH", default=1) or 0),
        help="Chunks to synthesize ahead of playback (default: 1)",
    )
    #
    parser.add_argument(
        "--channel",
        default=_env("PIPER_CHANNEL", default="default"),
        help="Preemption group on the server (default: default)",
    )
    parser.add_argument(
        "--no-preempt",
        action="store_true",
        help="Don't cancel audio that is already playing on the server",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_env_float("PIPER_TIMEOUT", default=30.0),
        help="Request timeout in seconds",
    )
    #
    parser.add_argument(
        "--player",
        default=_env("PIPER_PLAYER", default="auto"),
        help=(
            "Player command template reading raw PCM on stdin"
            " ({rate}, {channels}, {latency_ms}), or 'auto'"
        ),
    )
    parser.add_argument(
        "--player-latency-ms",
        type=int,
        default=int(_env_float("PIPER_PLAYER_LATENCY_MS", default=40) or 40),
        help="Playback buffer in milliseconds (default: 40)",
    )


def client_config_from_args(args: argparse.Namespace) -> ClientConfig:
    """Build a :class:`ClientConfig` from parsed arguments/environment."""
    overrides: Dict[str, Any] = {}
    if args.chunk_profile:
        overrides["profile"] = args.chunk_profile

    for name in (
        "chunk_max_words",
        "chunk_first_max_words",
        "chunk_min_words",
        "chunk_max_chars",
    ):
        value = getattr(args, name, None)
        if value is not None:
            overrides[name[len("chunk_") :]] = int(value)

    chunking = ChunkingConfig.from_mapping(overrides, base=ChunkingConfig())

    length_scale = args.length_scale
    if (length_scale is None) and (args.rate is not None):
        length_scale = rate_to_length_scale(
            args.rate, rate_factor=args.rate_factor or DEFAULT_RATE_FACTOR
        )

    volume = args.volume
    if (volume is None) and (args.sd_volume is not None):
        volume = sd_volume_to_multiplier(args.sd_volume)

    return ClientConfig(
        url=args.url,
        voice=normalize_voice_name(args.voice),
        speaker=args.speaker,
        speaker_id=args.speaker_id,
        length_scale=length_scale,
        noise_scale=args.noise_scale,
        noise_w_scale=args.noise_w_scale,
        volume=volume,
        normalize_audio=args.normalize_audio,
        sentence_silence=args.sentence_silence,
        chunk_silence=args.chunk_silence,
        chunking=chunking,
        chunk_mode=args.chunk_mode,
        prefetch=max(0, args.prefetch),
        channel=args.channel,
        preempt=not args.no_preempt,
        timeout=args.timeout,
    )


def main() -> int:
    """Run the command line client."""
    parser = argparse.ArgumentParser(
        prog="piper-client",
        description="Stream text to a Piper HTTP server and play it.",
    )
    parser.add_argument(
        "text", nargs="*", help="Text to speak (default: read from stdin)"
    )
    add_client_arguments(parser)
    parser.add_argument(
        "--output",
        choices=("play", "raw", "wav"),
        default="play",
        help="Play the audio (default), or write raw PCM/WAV to --output-file",
    )
    parser.add_argument(
        "-f",
        "--output-file",
        help="Where to write audio for --output raw/wav (default: stdout)",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop whatever is being synthesized on the server and exit",
    )
    parser.add_argument(
        "--info", action="store_true", help="Print server info and exit"
    )
    parser.add_argument(
        "--list-voices", action="store_true", help="List server voices and exit"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG messages to stderr"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING, stream=sys.stderr
    )

    config = client_config_from_args(args)
    client = PiperClient(config)

    if args.stop:
        client.stop()
        return 0

    if args.info:
        json.dump(client.info(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.list_voices:
        for voice_name in sorted(client.voices()):
            print(voice_name)

        return 0

    if args.text:
        text = " ".join(args.text)
    else:
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        return 0

    # speech-dispatcher (and anything else) stops us with SIGTERM/SIGINT:
    # playback and inference must end immediately.
    def handle_signal(signum: int, _frame: Any) -> None:
        _LOGGER.debug("Received signal %s, stopping", signum)
        client.stop()

    for signal_name in ("SIGTERM", "SIGINT", "SIGHUP"):
        signal_number = getattr(signal, signal_name, None)
        if signal_number is not None:
            try:
                signal.signal(signal_number, handle_signal)
            except ValueError:
                pass

    sink: Any
    if args.output == "play":  # pylint: disable=consider-using-with
        sink = AudioSink(
            PlayerConfig(command=args.player, latency_ms=args.player_latency_ms),
            sample_rate=client.sample_rate(),
        )
    else:
        output_file = (
            open(args.output_file, "wb")  # pylint: disable=consider-using-with
            if args.output_file
            else sys.stdout.buffer
        )
        if args.output == "wav":
            output_file.write(wav_header(client.sample_rate()))

        sink = FileSink(output_file)

    start_time = time.monotonic()
    try:
        completed = client.speak(text, sink)
    except BrokenPipeError:
        return 0
    except (OSError, RuntimeError) as error:
        if client.stopped:
            return 0

        print(f"piper-client: {error}", file=sys.stderr)
        return 1

    _LOGGER.debug(
        "%s in %.3fs",
        "Spoke" if completed else "Interrupted",
        time.monotonic() - start_time,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
