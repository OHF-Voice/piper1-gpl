"""Flask web server with HTTP API for Piper.

The server keeps voices loaded in memory and streams audio *while* it is being
synthesized, which is what makes it usable as a screen reader backend:

* ``POST /synthesize`` streams a WAV file (chunked transfer encoding) as soon as
  the first piece of audio exists.
* ``POST /stream`` streams raw 16-bit PCM, ready to be piped into a player.
* ``POST /stop`` immediately aborts synthesis and the output stream of active
  requests, freeing the engine for the next utterance.
* Requests can also be interrupted simply by closing the connection, and a new
  request on the same *channel* preempts the ones that are still running.

Long texts are split into small pieces before synthesis (see
:mod:`piper.chunking`) so that time-to-first-audio stays short and interruption
is nearly instantaneous. Every chunking parameter can be set per request or with
``--chunk-*`` options.
"""

import argparse
import io
import json
import logging
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.request import urlopen

from flask import Flask, Response, render_template, request

from . import PiperVoice, SynthesisConfig
from .chunking import PROFILES, ChunkingConfig, iter_chunks
from .download_voices import VOICES_JSON, download_voice

_LOGGER = logging.getLogger(__name__)

DEFAULT_CHANNEL = "default"

# Audio format of Piper output (all voices)
SAMPLE_WIDTH = 2
NUM_CHANNELS = 1


# -----------------------------------------------------------------------------
# Interruption
# -----------------------------------------------------------------------------


@dataclass
class Stream:
    """An in-flight synthesis request that can be cancelled."""

    stream_id: str
    channel: str
    group: str = ""
    """Utterance this stream belongs to: streams of the same group never
    preempt each other (a long text is sent as several requests)."""

    cancelled: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.monotonic)

    def cancel(self) -> None:
        self.cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()


class StreamRegistry:
    """Tracks active streams so they can be stopped or preempted.

    A *channel* groups streams that compete for the same pair of ears: a new
    request in a channel cancels the ones already running there. Screen readers
    need exactly this: moving the pointer to another area must silence the
    previous area immediately.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streams: Dict[str, Stream] = {}

    def start(
        self,
        channel: str = DEFAULT_CHANNEL,
        stream_id: Optional[str] = None,
        group: Optional[str] = None,
        preempt: bool = True,
    ) -> Stream:
        """Register a new stream, cancelling the ones it preempts.

        Streams of the same ``group`` (one utterance, possibly split over
        several requests) never cancel each other, whatever order they arrive
        in.
        """
        stream_id = stream_id or uuid.uuid4().hex
        stream = Stream(stream_id=stream_id, channel=channel, group=group or stream_id)
        to_cancel: List[Stream] = []
        with self._lock:
            # Same id twice: the newer request wins
            existing = self._streams.get(stream.stream_id)
            if existing is not None:
                to_cancel.append(existing)

            if preempt:
                to_cancel.extend(
                    other
                    for other in self._streams.values()
                    if (other.channel == channel)
                    and (other.group != stream.group)
                    and (other is not existing)
                )

            self._streams[stream.stream_id] = stream

        for other in to_cancel:
            _LOGGER.debug("Preempting stream %s", other.stream_id)
            other.cancel()

        return stream

    def finish(self, stream: Stream) -> None:
        with self._lock:
            if self._streams.get(stream.stream_id) is stream:
                del self._streams[stream.stream_id]

    def cancel(
        self,
        stream_id: Optional[str] = None,
        channel: Optional[str] = None,
        group: Optional[str] = None,
    ) -> List[str]:
        """Cancel streams by id, by group, by channel, or all of them.

        :return: ids of the cancelled streams.
        """
        with self._lock:
            if stream_id is not None:
                streams = [
                    s for s in self._streams.values() if s.stream_id == stream_id
                ]
            elif group is not None:
                streams = [s for s in self._streams.values() if s.group == group]
            elif channel is not None:
                streams = [s for s in self._streams.values() if s.channel == channel]
            else:
                streams = list(self._streams.values())

        for stream in streams:
            stream.cancel()

        return [stream.stream_id for stream in streams]

    def active(self) -> List[Dict[str, Any]]:
        with self._lock:
            streams = list(self._streams.values())

        now = time.monotonic()
        return [
            {
                "stream_id": stream.stream_id,
                "channel": stream.channel,
                "group": stream.group,
                "seconds": round(now - stream.started, 3),
                "cancelled": stream.is_cancelled,
            }
            for stream in streams
        ]


class Cancelled(Exception):
    """Raised internally when a stream is cancelled."""


# -----------------------------------------------------------------------------
# WAV streaming
# -----------------------------------------------------------------------------

# Length fields of a WAV file that is still being written. Players that stream
# from a pipe (aplay, ffplay, browsers) accept a "big enough" length and simply
# stop at end of stream.
_STREAMING_WAV_SIZE = 0x7FFFFFFF - 128


def wav_header(
    sample_rate: int,
    sample_width: int = SAMPLE_WIDTH,
    num_channels: int = NUM_CHANNELS,
    num_bytes: Optional[int] = None,
) -> bytes:
    """Build a 44-byte WAV header, for an unknown length by default."""
    data_size = _STREAMING_WAV_SIZE if num_bytes is None else num_bytes
    with io.BytesIO() as wav_io:
        wav_file: wave.Wave_write = wave.open(wav_io, "wb")
        with wav_file:
            wav_file.setframerate(sample_rate)
            wav_file.setsampwidth(sample_width)
            wav_file.setnchannels(num_channels)
            wav_file.writeframes(b"")

        header = bytearray(wav_io.getvalue()[:44])

    # RIFF size and data size
    header[4:8] = (data_size + 36).to_bytes(4, "little")
    header[40:44] = data_size.to_bytes(4, "little")
    return bytes(header)


# -----------------------------------------------------------------------------
# Voices
# -----------------------------------------------------------------------------


class VoiceManager:
    """Loads voices once and keeps them in memory."""

    def __init__(
        self,
        default_model_path: Path,
        data_dirs: Iterable[str],
        use_cuda: bool = False,
        include_alignments: bool = True,
    ) -> None:
        self.data_dirs = [Path(data_dir) for data_dir in data_dirs]
        self.use_cuda = use_cuda
        self.default_voice_id = default_model_path.name
        for suffix in (".onnx", ".onnx.json"):
            if self.default_voice_id.endswith(suffix):
                self.default_voice_id = self.default_voice_id[: -len(suffix)]
                break

        self._lock = threading.Lock()
        self._voices: Dict[str, PiperVoice] = {
            self.default_voice_id: PiperVoice.load(
                default_model_path,
                use_cuda=use_cuda,
                include_alignments=include_alignments,
            )
        }

        # One inference at a time per process: parallel ONNX runs on a CPU only
        # make every request slower, which is the opposite of what we want.
        self.inference_lock = threading.Lock()

    @property
    def default_voice(self) -> PiperVoice:
        return self._voices[self.default_voice_id]

    def get(self, voice_id: Optional[str]) -> Tuple[str, PiperVoice]:
        """Get a loaded voice by name, loading it on first use."""
        if (not voice_id) or (voice_id in ("no_voice", "NULL", "default")):
            # "no_voice" is what speech-dispatcher generic modules pass when the
            # client did not request a specific voice.
            return self.default_voice_id, self.default_voice

        with self._lock:
            voice = self._voices.get(voice_id)

        if voice is not None:
            return voice_id, voice

        for data_dir in self.data_dirs:
            model_path = data_dir / f"{voice_id}.onnx"
            if not model_path.exists():
                continue

            _LOGGER.debug("Loading voice %s", model_path)
            voice = PiperVoice.load(model_path, use_cuda=self.use_cuda)
            with self._lock:
                self._voices[voice_id] = voice

            return voice_id, voice

        _LOGGER.warning("Voice not found: %s. Using default voice.", voice_id)
        return self.default_voice_id, self.default_voice

    def loaded(self) -> List[str]:
        with self._lock:
            return sorted(self._voices)


# -----------------------------------------------------------------------------
# Request parsing
# -----------------------------------------------------------------------------


def _request_data() -> Dict[str, Any]:
    """Get parameters from a JSON body, a form, or the query string."""
    data: Dict[str, Any] = {}
    if request.args:
        data.update(request.args.to_dict())

    raw = b""
    if request.form:
        form = request.form.to_dict()
        only_key = next(iter(form)) if len(form) == 1 else None
        if (only_key is not None) and (form[only_key] == ""):
            # `curl -d '{"text": "..."}'` sends a body with a form content type
            # (that is curl's default), so werkzeug parses the whole body as a
            # single valueless key. Treat it as the raw body instead, otherwise
            # every parameter is silently dropped: `/stop` with a "stream_id"
            # would stop *every* stream.
            raw = only_key.encode("utf-8")
        else:
            data.update(form)

    if not raw:
        raw = request.get_data(cache=False)

    if raw:
        try:
            body = json.loads(raw)
            if isinstance(body, dict):
                data.update(body)
            elif isinstance(body, str):
                data["text"] = body
        except (ValueError, UnicodeDecodeError):
            # Plain text body
            data["text"] = raw.decode("utf-8", errors="replace")

    return data


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True

    if text in ("0", "false", "no", "off"):
        return False

    return default


def _as_float(value: Any, default: Optional[float]) -> Optional[float]:
    if value is None:
        return default

    return float(value)


# -----------------------------------------------------------------------------


def get_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(prog="piper.http_server")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP server host")
    parser.add_argument("--port", type=int, default=5000, help="HTTP server port")
    #
    parser.add_argument("-m", "--model", required=True, help="Path to Onnx model file")
    #
    parser.add_argument("-s", "--speaker", type=int, help="Id of speaker (default: 0)")
    parser.add_argument(
        "--length-scale", "--length_scale", type=float, help="Phoneme length"
    )
    parser.add_argument(
        "--noise-scale", "--noise_scale", type=float, help="Generator noise"
    )
    parser.add_argument(
        "--noise-w-scale",
        "--noise_w_scale",
        "--noise-w",
        "--noise_w",
        type=float,
        help="Phoneme width noise",
    )
    parser.add_argument(
        "--volume", type=float, default=1.0, help="Volume multiplier (default: 1.0)"
    )
    parser.add_argument(
        "--normalize",
        dest="normalize_audio",
        action="store_true",
        default=None,
        help="Always scale audio samples to the full range",
    )
    parser.add_argument(
        "--no-normalize",
        dest="normalize_audio",
        action="store_false",
        default=None,
        help="Never normalize audio",
    )
    #
    parser.add_argument("--cuda", action="store_true", help="Use GPU")
    #
    parser.add_argument(
        "--sentence-silence",
        "--sentence_silence",
        type=float,
        default=0.0,
        help="Seconds of silence after each sentence",
    )
    parser.add_argument(
        "--chunk-silence",
        "--chunk_silence",
        type=float,
        default=0.0,
        help="Seconds of silence between chunks of the same sentence (default: 0)",
    )
    #
    # Chunking (see piper.chunking). Defaults are tuned for responsiveness.
    parser.add_argument(
        "--chunk-profile",
        "--chunk_profile",
        default="responsive",
        choices=sorted(PROFILES),
        help="Text chunking preset (default: responsive, use 'off' to disable)",
    )
    parser.add_argument(
        "--chunk-max-words",
        "--chunk_max_words",
        type=int,
        help="Maximum words per synthesized chunk (0 = unlimited)",
    )
    parser.add_argument(
        "--chunk-first-max-words",
        "--chunk_first_max_words",
        type=int,
        help="Maximum words in the first chunk (lower = faster first audio)",
    )
    parser.add_argument(
        "--chunk-min-words",
        "--chunk_min_words",
        type=int,
        help="Minimum words before breaking at a clause boundary",
    )
    parser.add_argument(
        "--chunk-max-chars",
        "--chunk_max_chars",
        type=int,
        help="Hard limit on chunk length in characters (0 = unlimited)",
    )
    #
    parser.add_argument(
        "--no-preempt",
        action="store_true",
        help="Don't cancel running requests when a new one arrives on the same channel",
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Don't synthesize a warmup utterance at startup",
    )
    parser.add_argument(
        "--warmup-text",
        "--warmup_text",
        default="Piper is ready.",
        help="Text used for the (silent) warmup synthesis at startup",
    )
    #
    parser.add_argument(
        "--data-dir",
        "--data_dir",
        action="append",
        default=[str(Path.cwd())],
        help="Data directory to check for downloaded models (default: current directory)",
    )
    parser.add_argument(
        "--download-dir",
        "--download_dir",
        help="Path to download voices (default: first data dir)",
    )
    #
    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG messages to console"
    )
    return parser


def create_app(args: argparse.Namespace) -> Flask:
    """Load the voice(s) and build the Flask application."""
    _LOGGER.debug(args)

    if not args.download_dir:
        # Download voices to first data directory if not specified
        args.download_dir = args.data_dir[0]

    download_dir = Path(args.download_dir)

    # Download voice if file doesn't exist
    model_path = Path(args.model)
    if not model_path.exists():
        # Look in data directories
        voice_name = args.model
        for data_dir in args.data_dir:
            maybe_model_path = Path(data_dir) / f"{voice_name}.onnx"
            _LOGGER.debug("Checking '%s'", maybe_model_path)
            if maybe_model_path.exists():
                model_path = maybe_model_path
                break

    if not model_path.exists():
        raise ValueError(
            f"Unable to find voice: {model_path} in {maybe_model_path} (use piper.download_voices)"
        )

    # Default chunking for every request (may be overridden per request)
    default_chunking = ChunkingConfig.from_mapping(
        {
            "profile": args.chunk_profile,
            **{
                key: value
                for key, value in (
                    ("max_words", args.chunk_max_words),
                    ("first_max_words", args.chunk_first_max_words),
                    ("min_words", args.chunk_min_words),
                    ("max_chars", args.chunk_max_chars),
                )
                if value is not None
            },
        }
    )
    _LOGGER.debug("Chunking: %s", default_chunking)

    voices = VoiceManager(
        model_path,
        data_dirs=args.data_dir,
        use_cuda=args.cuda,
        include_alignments=True,
    )
    default_model_id = voices.default_voice_id
    default_voice = voices.default_voice
    streams = StreamRegistry()

    # Create web server.
    # Images live in the "img" directory and are served under "/img".
    app = Flask(__name__, static_folder="img", static_url_path="/img")

    # Info about the most recently synthesized utterance (for the web page).
    last_synthesis: Dict[str, Any] = {}

    # -------------------------------------------------------------------------

    def get_syn_config(
        data: Dict[str, Any], voice: PiperVoice, chunking: ChunkingConfig
    ) -> SynthesisConfig:
        """Build a synthesis config from request data, CLI args, voice config."""
        speaker_id: Optional[int] = data.get("speaker_id")
        if speaker_id is not None:
            speaker_id = int(speaker_id)

        if (voice.config.num_speakers > 1) and (speaker_id is None):
            speaker = data.get("speaker")
            if speaker:
                speaker_id = voice.config.speaker_id_map.get(speaker)

            if speaker_id is None:
                if speaker:
                    _LOGGER.warning(
                        "Speaker not found: '%s' in %s",
                        speaker,
                        voice.config.speaker_id_map.keys(),
                    )

                speaker_id = args.speaker or voice.config.default_speaker_id

        if (speaker_id is not None) and (speaker_id > voice.config.num_speakers):
            speaker_id = 0

        def scale(name: str, cli_value: Optional[float], voice_value: float) -> float:
            value = data.get(name)
            if value is None:
                value = cli_value if cli_value is not None else voice_value

            return float(value)

        # Normalization scales each synthesized piece to the full range, which
        # makes the loudness jump from chunk to chunk. It is therefore off by
        # default as soon as the text is chunked, unless asked for explicitly.
        normalize_audio = data.get("normalize_audio")
        if normalize_audio is None:
            normalize_audio = (
                args.normalize_audio
                if args.normalize_audio is not None
                else (not chunking.enabled)
            )

        return SynthesisConfig(
            speaker_id=speaker_id,
            length_scale=scale(
                "length_scale", args.length_scale, voice.config.length_scale
            ),
            noise_scale=scale(
                "noise_scale", args.noise_scale, voice.config.noise_scale
            ),
            noise_w_scale=scale(
                "noise_w_scale", args.noise_w_scale, voice.config.noise_w_scale
            ),
            normalize_audio=_as_bool(normalize_audio, True),
            volume=float(_as_float(data.get("volume"), args.volume) or 1.0),
        )

    def get_chunking(data: Dict[str, Any]) -> ChunkingConfig:
        """Per-request chunking config, falling back to the server defaults."""
        overrides: Dict[str, Any] = {}
        chunk_data = data.get("chunk")
        if isinstance(chunk_data, dict):
            overrides.update(chunk_data)
        elif isinstance(chunk_data, str):
            overrides["profile"] = chunk_data

        # Flat keys: chunk_max_words=3, ...
        for key, value in data.items():
            if key.startswith("chunk_") and (key != "chunk_silence"):
                overrides[key[len("chunk_") :]] = value

        if not overrides:
            return default_chunking

        return ChunkingConfig.from_mapping(overrides, base=default_chunking)

    def synthesize_stream(
        voice: PiperVoice,
        text: str,
        syn_config: SynthesisConfig,
        chunking: ChunkingConfig,
        stream: Stream,
        sentence_silence: float,
        chunk_silence: float,
    ) -> Iterator[bytes]:
        """Yield 16-bit PCM as it is synthesized, checking for cancellation.

        Cancellation is checked before every inference call and before every
        write, so a stop request takes effect within one chunk of audio (a few
        tens of milliseconds with the default chunking).
        """
        sample_rate = voice.config.sample_rate
        sentence_silence_bytes = bytes(int(sample_rate * sentence_silence) * 2)
        chunk_silence_bytes = bytes(int(sample_rate * chunk_silence) * 2)

        num_samples = 0
        completed = False
        start_time = time.monotonic()
        first_audio_seconds: Optional[float] = None
        phonemes: List[str] = []
        alignments: List[Dict[str, Any]] = []

        try:
            for chunk in iter_chunks(text, chunking):
                if stream.is_cancelled:
                    raise Cancelled

                if chunk.index > 0:
                    yield chunk_silence_bytes

                audio_chunks = _synthesize_chunk(voice, chunk.text, syn_config, stream)
                for sentence_idx, audio_chunk in enumerate(audio_chunks):
                    if stream.is_cancelled:
                        raise Cancelled

                    if sentence_idx > 0:
                        yield sentence_silence_bytes

                    if first_audio_seconds is None:
                        first_audio_seconds = time.monotonic() - start_time

                    num_samples += len(audio_chunk.audio_float_array)
                    phonemes.extend(audio_chunk.phonemes)
                    for alignment in audio_chunk.phoneme_alignments or []:
                        alignments.append(
                            {
                                "phoneme": alignment.phoneme,
                                "seconds": alignment.num_samples / sample_rate,
                            }
                        )

                    if chunk.is_last and (sentence_idx == (len(audio_chunks) - 1)):
                        # Everything has been synthesized. The generator is
                        # still suspended on this last yield, so the flag has to
                        # be set before it: a client that stops reading here has
                        # not interrupted anything.
                        completed = True

                    yield audio_chunk.audio_int16_bytes

            completed = True
        except Cancelled:
            _LOGGER.debug("Stream cancelled: %s", stream.stream_id)
        except GeneratorExit:
            if not completed:
                # Client disconnected early: interrupting by closing the
                # connection is a legitimate way to stop speech.
                stream.cancel()
                _LOGGER.debug("Stream closed by client: %s", stream.stream_id)

            raise
        finally:
            streams.finish(stream)
            total_seconds = time.monotonic() - start_time
            audio_seconds = num_samples / voice.config.sample_rate
            _LOGGER.debug(
                "Stream %s: first audio in %.3fs, %.3fs audio in %.3fs (%s)",
                stream.stream_id,
                first_audio_seconds if first_audio_seconds is not None else -1,
                audio_seconds,
                total_seconds,
                "complete" if completed else "cancelled",
            )
            last_synthesis.clear()
            last_synthesis.update(
                text=text,
                synthesize_seconds=total_seconds,
                first_audio_seconds=first_audio_seconds,
                audio_seconds=audio_seconds,
                cancelled=(not completed) and stream.is_cancelled,
                phonemes=phonemes,
                alignments=alignments,
            )

    def _synthesize_chunk(
        voice: PiperVoice,
        text: str,
        syn_config: SynthesisConfig,
        stream: Stream,
    ) -> List[Any]:
        """Synthesize one chunk of text while holding the inference lock.

        The lock is taken per chunk (not per request) so a preempted request
        releases the engine after at most one inference call, and it is never
        held while writing to the network: a slow or stalled client must not be
        able to block the engine.
        """
        with voices.inference_lock:
            if stream.is_cancelled:
                raise Cancelled

            audio_chunks: List[Any] = []
            for audio_chunk in voice.synthesize(
                text, syn_config, include_alignments=True
            ):
                audio_chunks.append(audio_chunk)
                if stream.is_cancelled:
                    break

            return audio_chunks

    def audio_response(data: Dict[str, Any], output_format: str) -> Response:
        """Build a streaming audio response from request data."""
        text = str(data.get("text") or "").strip()
        if not text:
            raise ValueError("No text provided")

        voice_id, voice = voices.get(data.get("voice"))
        chunking = get_chunking(data)
        syn_config = get_syn_config(data, voice, chunking)
        sample_rate = voice.config.sample_rate

        stream = streams.start(
            channel=str(data.get("channel") or DEFAULT_CHANNEL),
            stream_id=data.get("stream_id"),
            group=data.get("group"),
            preempt=_as_bool(data.get("preempt"), not args.no_preempt),
        )

        _LOGGER.debug(
            "Synthesizing (stream=%s, voice=%s, format=%s): '%s'",
            stream.stream_id,
            voice_id,
            output_format,
            text,
        )

        audio_stream = synthesize_stream(
            voice,
            text,
            syn_config,
            chunking,
            stream,
            sentence_silence=float(
                _as_float(data.get("sentence_silence"), args.sentence_silence) or 0.0
            ),
            chunk_silence=float(
                _as_float(data.get("chunk_silence"), args.chunk_silence) or 0.0
            ),
        )

        is_wav = output_format == "wav"
        mimetype = (
            "audio/wav"
            if is_wav
            else f"audio/L16; rate={sample_rate}; channels={NUM_CHANNELS}"
        )

        if not _as_bool(data.get("stream"), True):
            # Buffered response with a complete WAV header, for clients that
            # cannot consume a stream (e.g. <audio src> from a blob).
            audio_bytes = b"".join(audio_stream)
            body: Iterable[bytes] = [
                (
                    wav_header(sample_rate, num_bytes=len(audio_bytes)) + audio_bytes
                    if is_wav
                    else audio_bytes
                )
            ]
            response = Response(body, mimetype=mimetype)
        else:
            if is_wav:

                def with_header() -> Iterator[bytes]:
                    yield wav_header(sample_rate)
                    yield from audio_stream

                body = with_header()
            else:
                body = audio_stream

            response = Response(body, mimetype=mimetype, direct_passthrough=True)

        response.headers["X-Piper-Stream-Id"] = stream.stream_id
        response.headers["X-Piper-Voice"] = voice_id
        response.headers["X-Piper-Sample-Rate"] = str(sample_rate)
        response.headers["X-Piper-Sample-Width"] = str(SAMPLE_WIDTH)
        response.headers["X-Piper-Channels"] = str(NUM_CHANNELS)
        response.headers["Cache-Control"] = "no-store"
        # Don't let proxies buffer the stream
        response.headers["X-Accel-Buffering"] = "no"
        return response

    # -------------------------------------------------------------------------

    @app.errorhandler(ValueError)
    def app_bad_request(error: ValueError) -> Tuple[Dict[str, Any], int]:
        """Report bad requests as JSON, never as an HTML error page.

        Clients (screen readers) must be able to tell a bad request from a
        server failure without parsing HTML.
        """
        _LOGGER.debug("Bad request: %s", error)
        return {"error": str(error)}, 400

    @app.route("/", methods=["GET"])
    def app_index() -> str:
        """Web page for testing a voice in the browser."""
        return render_template("index.html")

    @app.route("/info", methods=["GET"])
    def app_info() -> Dict[str, Any]:
        """Info about the current voice and most recently synthesized utterance.

        Outputs a JSON object with the format:
        {
          "voice": {
            "name": "<voice name>",
            "language": "<espeak voice/alphabet>",
            "num_speakers": <number of speakers>,
            "sample_rate": <hertz>
          },
          "loaded_voices": ["<voice name>", ...],
          "chunking": { <default chunking config> },
          "streams": [ { "stream_id": ..., "channel": ... }, ... ],
          "last": {                            (null until something is synthesized)
            "text": "<synthesized text>",
            "synthesize_seconds": <wall-clock synthesis time>,
            "first_audio_seconds": <time to first audio chunk>,
            "audio_seconds": <duration of audio produced>,
            "cancelled": <true if interrupted>,
            "phonemes": ["<phoneme>", ...],
            "alignments": [
              { "phoneme": "<phoneme>", "seconds": <duration> },
              ...
            ]
          }
        }
        """
        return {
            "voice": {
                "name": default_model_id,
                "language": default_voice.config.espeak_voice,
                "num_speakers": default_voice.config.num_speakers,
                "sample_rate": default_voice.config.sample_rate,
                "sample_width": SAMPLE_WIDTH,
                "num_channels": NUM_CHANNELS,
            },
            "loaded_voices": voices.loaded(),
            "chunking": {
                "profile": args.chunk_profile,
                "max_words": default_chunking.max_words,
                "first_max_words": default_chunking.first_max_words,
                "min_words": default_chunking.min_words,
                "max_chars": default_chunking.max_chars,
                "enabled": default_chunking.enabled,
            },
            "streams": streams.active(),
            "last": last_synthesis or None,
        }

    @app.route("/voices", methods=["GET"])
    def app_voices() -> Dict[str, Any]:
        """List downloaded voices.

        Outputs a JSON object with the format:
        {
          "<voice name>": { <voice config> },
          ...
        }

        for each voice in your data directories.
        """
        voices_dict: Dict[str, Any] = {}
        config_paths: List[Path] = [Path(f"{model_path}.json")]

        for data_dir in args.data_dir:
            for onnx_path in Path(data_dir).glob("*.onnx"):
                config_path = Path(f"{onnx_path}.json")
                if config_path.exists():
                    config_paths.append(config_path)

        for config_path in config_paths:
            model_id = config_path.name
            for suffix in (".onnx.json", ".json"):
                if model_id.endswith(suffix):
                    model_id = model_id[: -len(suffix)]
                    break

            if model_id in voices_dict:
                continue

            with open(config_path, "r", encoding="utf-8") as config_file:
                voices_dict[model_id] = json.load(config_file)

        return voices_dict

    @app.route("/all-voices", methods=["GET"])
    def app_all_voices() -> Dict[str, Any]:
        """List all Piper voices.

        Outputs voices.json from the piper-voices repo on HuggingFace.
        See: https://huggingface.co/rhasspy/piper-voices
        """
        with urlopen(VOICES_JSON) as response:
            return json.load(response)

    @app.route("/download", methods=["POST"])
    def app_download() -> str:
        """Download a voice.

        Downloads the .onnx and .onnx.json file from piper-voices repo on HuggingFace.
        See: https://huggingface.co/rhasspy/piper-voices

        Expects a JSON object with the format:
        {
          "voice": "<voice name>",   (required)
          "force_redownload": false  (optional)
        }

        Returns the name of the voice.
        Voice format must be <language>-<name>-<quality> like "en_US-lessac-medium".
        """
        data = json.loads(request.data)
        model_id = data.get("voice")
        if not model_id:
            raise ValueError("voice is required")

        force_redownload = data.get("force_redownload", False)
        download_voice(model_id, download_dir, force_redownload=force_redownload)

        return model_id

    @app.route("/synthesize", methods=["POST", "GET"])
    @app.route("/", methods=["POST"])
    def app_synthesize() -> Response:
        """Synthesize audio from text and stream it as a WAV file.

        Audio starts flowing as soon as the first chunk of text has been
        synthesized; the response uses chunked transfer encoding.

        Expects a JSON object with the format:
        {
          "text": "Text to speak.",      (required)
          "voice": "<voice name>",       (optional)
          "speaker": "<speaker name>",   (optional)
          "speaker_id": "<speaker id>",  (optional, overrides speaker)
          "length_scale": 1.0,           (optional)
          "noise_scale": 0.667,          (optional)
          "noise_w_scale": 0.8,          (optional)
          "volume": 1.0,                 (optional)
          "normalize_audio": false,      (optional, default: false when chunked)
          "sentence_silence": 0.0,       (optional)
          "chunk_silence": 0.0,          (optional)
          "chunk": { ... },              (optional, see /stream)
          "stream_id": "<id>",           (optional, for /stop)
          "group": "<id>",               (optional, utterance id: streams of the
                                          same group never preempt each other)
          "channel": "<name>",           (optional, preemption group)
          "preempt": true,               (optional)
          "format": "wav" | "raw"        (optional)
        }

        The same fields may be passed as query parameters, and a plain text body
        is accepted as "text".
        """
        data = _request_data()
        output_format = str(data.get("format") or "wav").lower()
        if output_format in ("pcm", "raw", "l16"):
            output_format = "raw"
        elif request.accept_mimetypes.best in ("audio/pcm", "audio/l16", "audio/basic"):
            output_format = "raw"
        else:
            output_format = "wav"

        return audio_response(data, output_format)

    @app.route("/stream", methods=["POST", "GET"])
    def app_stream() -> Response:
        """Synthesize audio from text and stream raw 16-bit PCM.

        Same fields as /synthesize. The audio format is reported in the
        X-Piper-Sample-Rate, X-Piper-Sample-Width and X-Piper-Channels headers,
        and the id needed to stop this stream in X-Piper-Stream-Id.

        Example:
          curl -N -d '{"text": "Hello world."}' localhost:5000/stream \\
            | aplay -r 22050 -f S16_LE -t raw -
        """
        data = _request_data()
        return audio_response(data, "raw")

    @app.route("/stop", methods=["POST", "GET"])
    def app_stop() -> Dict[str, Any]:
        """Immediately stop synthesis and output of active streams.

        Expects (all optional) a JSON object with the format:
        {
          "stream_id": "<id>",   (stop only this stream)
          "group": "<id>",       (stop every stream of this utterance)
          "channel": "<name>"    (stop every stream of this channel)
        }

        With no parameters, every active stream is stopped.

        Inference stops before the next chunk, the HTTP response ends, and the
        engine is immediately available for the next request. The model stays
        loaded, so there is no warm-up cost afterwards.
        """
        data = _request_data()
        stopped = streams.cancel(
            stream_id=data.get("stream_id"),
            channel=data.get("channel"),
            group=data.get("group"),
        )
        _LOGGER.debug("Stopped streams: %s", stopped)
        return {"stopped": stopped, "num_stopped": len(stopped)}

    # -------------------------------------------------------------------------

    if not args.no_warmup:
        # Pay the first-inference cost (ONNX/CUDA lazy init) before any client
        # is waiting for audio.
        warmup_start = time.monotonic()
        num_warmup_samples = 0
        for audio_chunk in default_voice.synthesize(args.warmup_text):
            num_warmup_samples += len(audio_chunk.audio_float_array)

        _LOGGER.info(
            "Warmed up voice %s in %.3fs (%d samples discarded)",
            default_model_id,
            time.monotonic() - warmup_start,
            num_warmup_samples,
        )

    return app


def main() -> None:
    """Run HTTP server."""
    args = get_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    app = create_app(args)
    _LOGGER.info("Listening on http://%s:%s", args.host, args.port)

    # threaded=True is required: /stop must be handled while /synthesize is
    # still streaming.
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
