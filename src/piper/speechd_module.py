"""Speech Dispatcher output module for Piper.

Speech Dispatcher can drive Piper through its *generic* module (a shell command
per utterance), but a generic module cannot stop speech reliably and pays the
process startup cost every time. This module speaks the Speech Dispatcher
output module protocol directly and talks to a long-running
:mod:`piper.http_server`, which means:

* the voice model stays loaded (no warm-up per utterance),
* ``STOP``/``CANCEL`` interrupt playback *and* inference within a few tens of
  milliseconds, without restarting anything,
* text is chunked (see :mod:`piper.chunking`) so speech starts after a few
  words, and index marks are reported as they are reached.

Installation (no root required)::

    mkdir -p ~/.local/libexec/speech-dispatcher-modules
    ln -s "$(which sd_piper)" ~/.local/libexec/speech-dispatcher-modules/sd_piper
    mkdir -p ~/.config/speech-dispatcher/modules
    sd_piper --print-config > ~/.config/speech-dispatcher/modules/piper.conf

Speech Dispatcher discovers ``sd_<name>`` binaries in that directory and passes
``<name>.conf`` as the only argument. See docs/SPEECHD.md.

Protocol reference: the module reads commands from stdin and writes replies and
events to stdout, LF-terminated, UTF-8. stderr is free-form logging (Speech
Dispatcher redirects it to ``<LogDir>/piper.log``).
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from queue import Empty, Queue
from typing import IO, Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

try:
    import fcntl
except ImportError:  # pragma: no cover - not Linux
    fcntl = None  # type: ignore[assignment]

from .chunking import PROFILES, ChunkingConfig, TextChunk
from .client import (
    DEFAULT_RATE_FACTOR,
    DEFAULT_URL,
    AudioSink,
    ClientConfig,
    PiperClient,
    PlayerConfig,
    rate_to_length_scale,
    sd_volume_to_multiplier,
)

_LOGGER = logging.getLogger("piper.speechd")

MODULE_NAME = "piper"

# Speech Dispatcher inserts these marks between sentences
SPD_MARK_PREFIX = "__spd_"

# Maximum size of one 705 audio block (matches module_tts_output_server)
MAX_AUDIO_BLOCK = 10000

# HDLC-style escaping used for audio sent to the server
ESCAPE_BYTE = 0x7D
ESCAPE_MASK = 0x20
ESCAPED_BYTES = (0x0A, ESCAPE_BYTE)

# Autostart
#: Hosts we may start a server for (starting a *remote* server is impossible).
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})

#: systemd user unit looked up before starting anything ourselves.
DEFAULT_SERVER_SERVICE = "piper-server.service"

#: Transient unit name used with ``systemd-run`` (port appended).
TRANSIENT_UNIT_PREFIX = "piper-server"

#: How long to wait before trying to start the server again after a failure.
START_RETRY_SECONDS = 30.0

#: Timeout of the "is the server there?" request (it must never delay speech).
PROBE_TIMEOUT = 2.0

SERVICE_UNIT = """# Piper text-to-speech server (Speech Dispatcher backend)
#
# Install:
#   sd_piper --print-service > ~/.config/systemd/user/piper-server.service
#   systemctl --user daemon-reload
#   systemctl --user enable --now piper-server.service
#
# The Piper output module starts this unit on demand, so "enable" is optional:
# it only makes the very first utterance after login fast.

[Unit]
Description=Piper text-to-speech server
Documentation=https://github.com/OHF-voice/piper1-gpl
Before=speech-dispatcher.service
# A missing voice or a bad option cannot be fixed by restarting: stop trying
# after a few attempts instead of looping (journalctl --user -u piper-server).
StartLimitIntervalSec=600
StartLimitBurst=5

[Service]
Type=exec
# Paths must be absolute: systemd does not expand "~".
ExecStart={command}
Restart=on-failure
# Back off progressively (2s, 5s, 11s, 26s, 60s) instead of hammering the
# machine when the server cannot start. RestartSteps and RestartMaxDelaySec
# need systemd 254; older versions just use RestartSec.
RestartSec=2
RestartSteps=5
RestartMaxDelaySec=60
# Speech must never wait behind other work.
Nice=-5
# The model is loaded once and stays in memory.
TimeoutStopSec=5

[Install]
WantedBy=default.target
"""


EXAMPLE_CONFIG = """# Piper output module for Speech Dispatcher (native module, sd_piper)
#
# Install:
#   mkdir -p ~/.config/speech-dispatcher/modules
#   sd_piper --print-config > ~/.config/speech-dispatcher/modules/piper.conf
#   mkdir -p ~/.local/libexec/speech-dispatcher-modules
#   ln -sf "$(command -v sd_piper)" ~/.local/libexec/speech-dispatcher-modules/sd_piper
#
# Speech Dispatcher then discovers the module automatically as "piper".
# See docs/SPEECHD.md.

# Where piper.http_server is listening.
PiperURL "http://localhost:5000"

# Audio output:
#   player - this module plays audio itself (default). Interruption drops
#            buffered audio immediately, which is what a screen reader needs.
#   server - hand PCM back to Speech Dispatcher and let it play (uses the
#            AudioOutputMethod from speechd.conf).
PiperAudio player

# Player command used in "player" mode. "auto" picks the first available of
# pw-play, paplay, aplay, ffplay. {rate}, {channels} and {latency_ms} are
# substituted; the command must read raw PCM on stdin.
PiperPlayer "auto"

# Playback buffer. Lower = speech stops sooner after STOP, but drop-outs become
# more likely on a loaded machine.
PiperPlayerLatencyMs 40

# Chunking: how text is split before synthesis. This is the main
# latency/quality trade-off, tune it to taste.
#   instant    - start after 2 words, chunks of 3 (fastest, most artifacts)
#   responsive - start after 3 words, chunks of 5 (default)
#   balanced   - start after 4 words, chunks of 10
#   smooth     - only split at sentences (best prosody, slowest start)
#   off        - no splitting at all
PiperChunkProfile responsive

# Individual chunking knobs (override the profile).
#PiperChunkMaxWords 5
#PiperChunkFirstMaxWords 3
#PiperChunkMinWords 2
#PiperChunkMaxChars 0
#PiperChunkAbbreviations "mr,mrs,dr,prof,etc"

# Number of chunks synthesized ahead of playback.
PiperPrefetch 1

# Insert a little silence between chunks if you hear clicks at chunk
# boundaries (seconds).
#PiperChunkSilence 0.02
#PiperSentenceSilence 0.0

# Speech rate mapping: rate=+100 is this many times faster than rate=0,
# rate=-100 this many times slower. Screen reader users often want 3 or more.
PiperRateFactor 3.0

# Length scale used at rate=0 (< 1 is faster).
#PiperLengthScale 1.0

# Starting the server
# -------------------
# The server is started on demand when it is not already running (the first
# utterance then waits for the model to load). The best setup is still to run
# it as a user service, so it is ready before the screen reader speaks:
#
#   sd_piper --print-service > ~/.config/systemd/user/piper-server.service
#   systemctl --user daemon-reload && systemctl --user enable --now piper-server
#
#   auto - start it if PiperURL is local and it does not answer (default)
#   yes  - same, and complain in the log when it is not possible
#   no   - never start anything; only use a server that is already running
PiperAutostart auto

# How to start it:
#   auto    - systemd user service if available, otherwise a plain process
#   systemd - only systemd (the unit below, or a transient one)
#   process - only a detached child process
PiperServerManager auto

# systemd user unit started when it exists. Use "none" to always start a
# transient unit / plain process instead.
PiperServerService "piper-server.service"

# Command used to start the server ("~" is expanded). The default is derived
# from DefaultVoice:
#   python3 -m piper.http_server --host 127.0.0.1 --port 5000 --model <voice>
#PiperServerCommand "python3 -m piper.http_server -m /home/user/.piper-voices/en_US-kristin-medium.onnx"

# How long the first utterance waits for the server (seconds).
PiperServerTimeout 20

# Voices: AddVoice <language> <symbolic voice> <Piper voice name>
# The Piper voice name is what the server knows (see: curl localhost:5000/voices).
AddVoice "en-US" "FEMALE1" "en_US-kristin-medium"
#AddVoice "en-US" "MALE1"   "en_US-ryan-medium"
#AddVoice "fr-FR" "FEMALE1" "fr_FR-siwis-medium"

# Voice used when the client does not ask for anything specific.
DefaultVoice "en_US-kristin-medium"
"""


# -----------------------------------------------------------------------------
# Module configuration file
# -----------------------------------------------------------------------------


#: Chunking options of the module config file -> ChunkingConfig fields
_CHUNK_OPTIONS = {
    "piperchunkprofile": "profile",
    "piperchunkenabled": "enabled",
    "piperchunkmaxwords": "max_words",
    "piperchunkfirstmaxwords": "first_max_words",
    "piperchunkminwords": "min_words",
    "piperchunkmaxchars": "max_chars",
    "piperchunkmergeshorttail": "merge_short_tail",
    "piperchunkbreakonsentence": "break_on_sentence",
    "piperchunkbreakonclause": "break_on_clause",
    "piperchunksentencepunctuation": "sentence_punctuation",
    "piperchunkclausepunctuation": "clause_punctuation",
    "piperchunkabbreviations": "abbreviations",
    "piperchunkstripurls": "strip_urls",
}


@dataclass
class VoiceEntry:
    """An ``AddVoice`` entry: language, symbolic voice type, Piper voice name."""

    language: str
    voice_type: str
    name: str

    @property
    def variant(self) -> str:
        return "none"


@dataclass
class ModuleConfig:
    """Options read from the module configuration file."""

    url: str = DEFAULT_URL
    default_voice: Optional[str] = None
    voices: List[VoiceEntry] = field(default_factory=list)
    #
    audio_output: str = "player"
    """``player`` (this module plays audio, default) or ``server`` (hand PCM
    back to Speech Dispatcher, which plays it)."""

    player: str = "auto"
    player_latency_ms: int = 40
    #
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    chunk_mode: str = "client"
    prefetch: int = 1
    channel: str = "speech-dispatcher"
    #
    rate_factor: float = DEFAULT_RATE_FACTOR
    base_length_scale: float = 1.0
    sentence_silence: Optional[float] = None
    chunk_silence: Optional[float] = None
    normalize_audio: Optional[bool] = None
    noise_scale: Optional[float] = None
    noise_w_scale: Optional[float] = None
    #
    autostart: str = "auto"
    """``auto`` (start a local server on demand, default), ``yes`` (same, but
    complain if it cannot be done) or ``no``."""

    server_manager: str = "auto"
    """How the server is started: ``auto`` (systemd if available, otherwise a
    plain process), ``systemd``, ``process`` or ``none``."""

    server_service: str = DEFAULT_SERVER_SERVICE
    """systemd user unit to start if it exists (``none`` to ignore units)."""

    server_command: Optional[str] = None
    """Command used to start the server (default: derived from the voice)."""

    server_timeout: float = 20.0
    """How long to wait for the server to answer after starting it."""
    #
    log_level: int = 3

    @staticmethod
    def load(config_path: Optional[str]) -> "ModuleConfig":
        """Parse a Speech Dispatcher style module config file.

        Unknown options are ignored so the same file can also be used by the
        generic module.
        """
        config = ModuleConfig()
        chunk_overrides: Dict[str, Any] = {}

        if not config_path:
            return config

        try:
            with open(config_path, "r", encoding="utf-8") as config_file:
                lines = config_file.readlines()
        except OSError as error:
            _LOGGER.warning("Cannot read config %s: %s", config_path, error)
            return config

        for line in lines:
            line = line.strip()
            if (not line) or line.startswith("#"):
                continue

            try:
                parts = shlex.split(line, comments=True)
            except ValueError:
                _LOGGER.warning("Ignoring unparsable config line: %s", line)
                continue

            if not parts:
                continue

            key, values = parts[0].lower(), parts[1:]
            value = values[0] if values else ""

            if key == "addvoice" and (len(values) >= 3):
                config.voices.append(
                    VoiceEntry(
                        language=values[0], voice_type=values[1].upper(), name=values[2]
                    )
                )
            elif key in ("defaultvoice", "pipervoice"):
                config.default_voice = value
            elif key in ("piperurl", "url"):
                config.url = value
            elif key == "piperaudio":
                config.audio_output = value.lower()
            elif key == "piperplayer":
                config.player = value
            elif key == "piperplayerlatencyms":
                config.player_latency_ms = int(value)
            elif key in _CHUNK_OPTIONS:
                chunk_overrides[_CHUNK_OPTIONS[key]] = value
            elif key == "piperchunkmode":
                config.chunk_mode = value.lower()
            elif key == "piperprefetch":
                config.prefetch = int(value)
            elif key == "piperchannel":
                config.channel = value
            elif key == "piperratefactor":
                config.rate_factor = float(value)
            elif key == "piperlengthscale":
                config.base_length_scale = float(value)
            elif key == "pipersentencesilence":
                config.sentence_silence = float(value)
            elif key == "piperchunksilence":
                config.chunk_silence = float(value)
            elif key == "pipernormalize":
                config.normalize_audio = value.lower() in ("1", "true", "yes", "on")
            elif key == "pipernoisescale":
                config.noise_scale = float(value)
            elif key == "pipernoisewscale":
                config.noise_w_scale = float(value)
            elif key == "piperautostart":
                config.autostart = _autostart_mode(value)
            elif key == "piperservermanager":
                config.server_manager = value.lower()
            elif key == "piperserverservice":
                config.server_service = value
            elif key == "piperservercommand":
                config.server_command = " ".join(values)
            elif key == "piperservertimeout":
                config.server_timeout = float(value)

        if chunk_overrides:
            config.chunking = ChunkingConfig.from_mapping(
                chunk_overrides, base=config.chunking
            )

        return config


# -----------------------------------------------------------------------------
# Starting the server
# -----------------------------------------------------------------------------


def _autostart_mode(value: str) -> str:
    """Normalize ``PiperAutostart`` (``1``/``0`` are accepted for old configs)."""
    lowered = value.strip().lower()
    if lowered in ("0", "no", "off", "false", "never"):
        return "no"

    if lowered in ("1", "yes", "on", "true", "always"):
        return "yes"

    return "auto"


def split_url(url: str) -> Tuple[str, int]:
    """Return ``(host, port)`` of a server URL."""
    parts = urlsplit(url if "//" in url else f"http://{url}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return (parts.hostname or "localhost"), port


def is_local_url(url: str) -> bool:
    """True if a server for this URL could run on this machine."""
    host, _port = split_url(url)
    return host.lower() in LOCAL_HOSTS


def default_server_command(config: ModuleConfig) -> Optional[List[str]]:
    """Build the command that starts a server matching this configuration.

    ``None`` if no voice is configured, in which case the server cannot be
    started without an explicit ``PiperServerCommand``.
    """
    voice = config.default_voice or (config.voices[0].name if config.voices else None)
    if not voice:
        return None

    host, port = split_url(config.url)
    return [
        sys.executable or "python3",
        "-m",
        "piper.http_server",
        "--host",
        "127.0.0.1" if host.lower() in ("localhost", "0.0.0.0", "") else host,
        "--port",
        str(port),
        "--model",
        voice,
    ]


def expand_user(argument: str) -> str:
    """Expand a leading ``~``, including after ``=`` (``--data-dir=~/voices``).

    Speech Dispatcher configuration files are not read by a shell, so nothing
    else expands the home directory.
    """
    if argument.startswith("~"):
        return os.path.expanduser(argument)

    option, separator, value = argument.partition("=")
    if separator and value.startswith("~"):
        return f"{option}={os.path.expanduser(value)}"

    return argument


def server_command(config: ModuleConfig) -> Optional[List[str]]:
    """The configured start command, or the derived one."""
    if config.server_command:
        try:
            return [expand_user(part) for part in shlex.split(config.server_command)]
        except ValueError:
            _LOGGER.error("Cannot parse PiperServerCommand: %s", config.server_command)
            return None

    return default_server_command(config)


def _run(command: Sequence[str], timeout: float = 10.0) -> Optional[str]:
    """Run a helper command; return its stderr on success, None on failure."""
    try:
        result = subprocess.run(  # pylint: disable=subprocess-run-check
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _LOGGER.debug("%s failed: %s", command[0], error)
        return None

    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        _LOGGER.debug("%s exited with %s: %s", command[0], result.returncode, stderr)
        return None

    return stderr


def systemd_user_available() -> bool:
    """True if there is a systemd user manager we can talk to."""
    return bool(os.environ.get("XDG_RUNTIME_DIR")) and (
        shutil.which("systemctl") is not None
    )


def _unit_failed(unit: str) -> bool:
    """True if a systemd user unit gave up starting."""
    return (
        _run(["systemctl", "--user", "is-failed", "--quiet", "--", unit], timeout=5.0)
        is not None
    )


def server_log_path() -> str:
    """Where a self-started server writes its log."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "piper", "http_server.log")


def _open_server_log() -> Optional[IO[bytes]]:
    """Open the server log, or None if it cannot be written."""
    path = server_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return open(path, "ab", buffering=0)  # pylint: disable=consider-using-with
    except OSError as error:
        _LOGGER.debug("Cannot write %s: %s", path, error)
        return None


class StartLock:
    """Advisory lock so that two modules never start two servers.

    Held only while the server is being started. If another process holds it,
    that process is starting the server and we simply wait for it.
    """

    def __init__(self, port: int) -> None:
        directory = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        self.path = os.path.join(directory, f"piper-server-{port}.lock")
        self._file: Optional[Any] = None

    def __enter__(self) -> bool:
        """True if we own the lock (or if locking is unavailable)."""
        if fcntl is None:
            return True

        try:
            # pylint: disable=consider-using-with
            self._file = open(self.path, "a", encoding="utf-8")
        except OSError as error:
            # No lock file: starting the server is still better than not
            # speaking at all (the server itself refuses a second bind).
            _LOGGER.debug("Cannot use %s: %s", self.path, error)
            return True

        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _LOGGER.debug("Another process is starting the server")
            self._close()
            return False
        except OSError as error:
            _LOGGER.debug("Cannot lock %s: %s", self.path, error)
            return True

        return True

    def __exit__(self, *_exception: Any) -> None:
        self._close()

    def _close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass

            self._file = None


# -----------------------------------------------------------------------------
# SSML
# -----------------------------------------------------------------------------

_ENTITIES = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"))


def parse_ssml(message: str) -> Tuple[str, List[Tuple[int, str]]]:
    """Extract plain text and index marks from a Speech Dispatcher message.

    Speech Dispatcher always sends SSML, with ``<mark name="__spd_N"/>`` markers
    inserted between sentences.

    :return: (text, [(offset in text, mark name), ...])
    """
    text_parts: List[str] = []
    marks: List[Tuple[int, str]] = []
    length = 0
    index = 0
    message_length = len(message)

    while index < message_length:
        start = message.find("<", index)
        if start < 0:
            chunk = _unescape(message[index:])
            text_parts.append(chunk)
            length += len(chunk)
            break

        if start > index:
            chunk = _unescape(message[index:start])
            text_parts.append(chunk)
            length += len(chunk)

        end = message.find(">", start)
        if end < 0:
            # Unterminated tag: treat the rest as text
            chunk = _unescape(message[start:])
            text_parts.append(chunk)
            length += len(chunk)
            break

        tag = message[start + 1 : end]
        if tag.lstrip("/").lower().startswith("mark"):
            name = _tag_attribute(tag, "name")
            if name:
                marks.append((length, name))

        index = end + 1

    return "".join(text_parts), marks


def _unescape(text: str) -> str:
    # &amp; last so "&amp;lt;" does not become "<"
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)

    return text.replace("&amp;", "&")


def _tag_attribute(tag: str, name: str) -> Optional[str]:
    lowered = tag.lower()
    position = lowered.find(name.lower() + "=")
    if position < 0:
        return None

    rest = tag[position + len(name) + 1 :].lstrip()
    if not rest:
        return None

    quote = rest[0]
    if quote in ("'", '"'):
        end = rest.find(quote, 1)
        return rest[1:end] if end > 0 else None

    return rest.split()[0].rstrip("/")


# -----------------------------------------------------------------------------
# Audio sinks
# -----------------------------------------------------------------------------


def escape_audio(audio_bytes: bytes) -> bytes:
    """Escape PCM for a 705 AUDIO block (0x0A and 0x7D are escaped)."""
    if not any(byte in audio_bytes for byte in ESCAPED_BYTES):
        return audio_bytes

    escaped = bytearray()
    for byte in audio_bytes:
        if byte in ESCAPED_BYTES:
            escaped.append(ESCAPE_BYTE)
            escaped.append(byte ^ ESCAPE_MASK)
        else:
            escaped.append(byte)

    return bytes(escaped)


class ServerAudioSink:
    """Sends PCM back to Speech Dispatcher as ``705 AUDIO`` blocks."""

    def __init__(self, writer: "ProtocolWriter", sample_rate: int) -> None:
        self._writer = writer
        self._sample_rate = sample_rate

    def write(self, audio_bytes: bytes) -> None:
        for offset in range(0, len(audio_bytes), MAX_AUDIO_BLOCK):
            block = audio_bytes[offset : offset + MAX_AUDIO_BLOCK]
            self._writer.write_audio(block, self._sample_rate)

    def drain(self, timeout: Optional[float] = None) -> None:
        pass

    def stop(self) -> None:
        pass


# -----------------------------------------------------------------------------
# Protocol I/O
# -----------------------------------------------------------------------------


class ProtocolWriter:
    """Writes protocol replies and events, one complete message at a time.

    A single lock guarantees that an asynchronous event never splits a
    multi-line reply, which Speech Dispatcher treats as a fatal error.
    """

    def __init__(self, output: Any) -> None:
        self._output = output
        self._lock = threading.Lock()

    def write_lines(self, *lines: str) -> None:
        data = "".join(f"{line}\n" for line in lines).encode("utf-8")
        with self._lock:
            self._output.write(data)
            self._output.flush()

    def write_audio(self, audio_bytes: bytes, sample_rate: int) -> None:
        """Write one ``705 AUDIO`` block (binary, HDLC-escaped)."""
        num_samples = len(audio_bytes) // 2
        header = (
            f"705-bits=16\n"
            f"705-num_channels=1\n"
            f"705-sample_rate={sample_rate}\n"
            f"705-num_samples={num_samples}\n"
            f"705-big_endian=0\n"
            f"705-AUDIO"
        ).encode("utf-8")
        with self._lock:
            self._output.write(header)
            self._output.write(b"\0")
            self._output.write(escape_audio(audio_bytes))
            self._output.write(b"\n705 AUDIO\n")
            self._output.flush()


# -----------------------------------------------------------------------------
# The module
# -----------------------------------------------------------------------------


@dataclass
class Utterance:
    """One message to speak, with its own cancellation token."""

    text: str
    marks: List[Tuple[int, str]] = field(default_factory=list)
    group: str = ""
    chunking: Optional[ChunkingConfig] = None
    """Chunking to use for this message (None = the module default)."""

    cancelled: threading.Event = field(default_factory=threading.Event)
    paused: bool = False

    started: bool = False
    """True once ``701 BEGIN`` has been sent for this message."""

    def cancel(self, pause: bool = False) -> None:
        self.paused = pause
        self.cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()


class PiperSpeechdModule:
    """Speech Dispatcher output module backed by the Piper HTTP server."""

    def __init__(
        self,
        config: ModuleConfig,
        stdin: Any = None,
        stdout: Any = None,
    ) -> None:
        self.config = config
        self._stdin = stdin if stdin is not None else sys.stdin.buffer
        self._writer = ProtocolWriter(
            stdout if stdout is not None else sys.stdout.buffer
        )

        # Voice parameters from SET
        self._rate = 0.0
        self._volume = 100.0
        self._voice_type = "FEMALE1"
        self._language: Optional[str] = None
        self._synthesis_voice: Optional[str] = None

        self._client = PiperClient(self._client_config())
        self._sample_rate = 22050
        self._server_audio = False

        # Server startup. The flag is the fast path: it is only cleared when
        # the server turns out to be gone, so speaking costs no extra request.
        self._server_process: Optional[subprocess.Popen] = None
        self._server_unit: Optional[str] = None
        self._server_ready = threading.Event()
        self._server_lock = threading.Lock()
        self._retry_server_at = 0.0

        self._queue: "Queue[Optional[Utterance]]" = Queue()
        self._current_lock = threading.Lock()
        self._current: Optional[Utterance] = None
        self._quit = threading.Event()
        self._worker = threading.Thread(target=self._speak_loop, daemon=True)

    # -- configuration ----------------------------------------------------

    def _client_config(self) -> ClientConfig:
        return ClientConfig(
            url=self.config.url,
            voice=self._current_voice(),
            length_scale=rate_to_length_scale(
                self._rate,
                base_length_scale=self.config.base_length_scale,
                rate_factor=self.config.rate_factor,
            ),
            noise_scale=self.config.noise_scale,
            noise_w_scale=self.config.noise_w_scale,
            volume=sd_volume_to_multiplier(self._volume),
            normalize_audio=self.config.normalize_audio,
            sentence_silence=self.config.sentence_silence,
            chunk_silence=self.config.chunk_silence,
            chunking=self.config.chunking,
            chunk_mode=self.config.chunk_mode,
            prefetch=self.config.prefetch,
            channel=self.config.channel,
        )

    def _current_voice(self) -> Optional[str]:
        """Resolve the Piper voice name from the current SET parameters."""
        if self._synthesis_voice:
            return self._synthesis_voice

        # Symbolic voice type + language, as configured with AddVoice
        candidates = self.config.voices
        if self._language:
            language = self._language.lower()
            matching = [
                voice for voice in candidates if voice.language.lower() == language
            ]
            if not matching:
                # Match just the language part ("en" for "en-GB")
                prefix = language.split("-")[0]
                matching = [
                    voice
                    for voice in candidates
                    if voice.language.lower().split("-")[0] == prefix
                ]

            if matching:
                candidates = matching

        for voice in candidates:
            if voice.voice_type == self._voice_type:
                return voice.name

        if candidates:
            return candidates[0].name

        return self.config.default_voice

    def _voice_list(self) -> List[Tuple[str, str, str]]:
        """Voices to report for ``LIST VOICES`` (at least one, always)."""
        voices: List[Tuple[str, str, str]] = []
        seen = set()

        for entry in self.config.voices:
            if entry.name in seen:
                continue

            seen.add(entry.name)
            voices.append((entry.name, entry.language, entry.variant))

        try:
            for name, voice_config in sorted(self._client.voices().items()):
                if name in seen:
                    continue

                seen.add(name)
                language = _voice_language(name, voice_config)
                voices.append((name, language, "none"))
        except (OSError, RuntimeError, ValueError) as error:
            _LOGGER.warning("Cannot list server voices: %s", error)

        if not voices:
            name = self.config.default_voice or MODULE_NAME
            voices.append((name, "en-US", "none"))

        return voices

    # -- server -----------------------------------------------------------

    def _server_is_up(self) -> bool:
        """Probe the server, remembering its sample rate.

        The probe uses its own short-lived client: it must not disturb (or wait
        as long as) a synthesis request, and it may run while the worker thread
        is speaking.
        """
        try:
            probe = PiperClient(replace(self._client_config(), timeout=PROBE_TIMEOUT))
            info = probe.info()
            self._sample_rate = int(info["voice"]["sample_rate"])
            return True
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            _LOGGER.debug("Server not available: %s", error)
            return False

    def _autostart_wanted(self) -> bool:
        mode = self.config.autostart
        if (mode == "no") or (self.config.server_manager == "none"):
            return False

        if not is_local_url(self.config.url):
            # Nothing we can do about a server on another machine.
            log = _LOGGER.warning if mode == "yes" else _LOGGER.debug
            log("Not starting a server: %s is not local", self.config.url)
            return False

        return True

    def ensure_server(self, cancel: Optional[threading.Event] = None) -> bool:
        """Make sure the server is running, starting it if necessary.

        Idempotent and safe to call from any thread: the first caller does the
        work while the others wait on the same lock, so a burst of utterances
        can never start two servers. ``cancel`` (the current utterance's stop
        token) aborts the wait early.
        """
        if self._server_ready.is_set():
            return True

        # Someone else may already be starting the server (the background
        # thread from INIT, typically): wait for it, but stay interruptible.
        # pylint: disable=consider-using-with
        while not self._server_lock.acquire(timeout=0.1):
            if self._server_ready.is_set():
                return True

            if self._aborted(cancel):
                return False

        try:
            if self._server_ready.is_set():
                return True

            if self._server_is_up():
                self._server_ready.set()
                return True

            if not self._autostart_wanted():
                return False

            if time.monotonic() < self._retry_server_at:
                # A recent attempt failed: fail fast instead of making every
                # utterance wait for the same timeout again.
                return False

            if self._start_server(cancel=cancel):
                self._server_ready.set()
                return True

            if not self._aborted(cancel):
                # Genuine failure (not "the user pressed stop while we waited").
                self._retry_server_at = time.monotonic() + START_RETRY_SECONDS

            return False
        finally:
            self._server_lock.release()

    def _aborted(self, cancel: Optional[threading.Event] = None) -> bool:
        """True if waiting for the server was interrupted rather than failed."""
        return self._quit.is_set() or ((cancel is not None) and cancel.is_set())

    def server_lost(self) -> None:
        """Forget that the server was up, so the next utterance re-checks it."""
        self._server_ready.clear()

    def _start_server(self, cancel: Optional[threading.Event] = None) -> bool:
        """Start the server and wait for it to answer."""
        command = server_command(self.config)
        if not command:
            _LOGGER.error(
                "Cannot start a server: no voice configured "
                "(add DefaultVoice or PiperServerCommand to the module config)"
            )
            return False

        _, port = split_url(self.config.url)
        with StartLock(port) as owned:
            if not owned:
                # Another module instance is already starting the same
                # server: wait for it instead of starting a second one.
                return self._wait_for_server(cancel=cancel)

            manager = self.config.server_manager
            started = False
            if manager in ("auto", "systemd"):
                started = self._start_with_systemd(command)

            if (not started) and (manager in ("auto", "process")):
                started = self._spawn(command)

            if not started:
                return False

            # The lock is held until the server answers, so a module starting at
            # the same time waits for this server instead of starting its own.
            if self._wait_for_server(cancel=cancel):
                _LOGGER.info("Piper server is ready at %s", self.config.url)
                return True

        if not self._aborted(cancel):
            _LOGGER.error(
                "Piper server did not answer at %s within %.0fs (see %s)",
                self.config.url,
                self.config.server_timeout,
                server_log_path(),
            )

        return False

    def _start_with_systemd(self, command: Sequence[str]) -> bool:
        """Start the server as a systemd user unit.

        Preferred when available: systemd owns the process, so it survives this
        module, is restarted if it crashes, is stopped at logout, and starting
        an already-running unit is a no-op — no locking needed.
        """
        if not systemd_user_available():
            return False

        unit = self.config.server_service.strip()
        if unit and (unit.lower() not in ("none", "off", "")):
            if _run(["systemctl", "--user", "cat", "--", unit]) is not None:
                _LOGGER.info("Starting systemd user unit %s", unit)
                self._server_unit = unit
                return _run(["systemctl", "--user", "start", "--", unit]) is not None

        if shutil.which("systemd-run") is None:
            return False

        _, port = split_url(self.config.url)
        transient = f"{TRANSIENT_UNIT_PREFIX}-{port}"
        _LOGGER.debug("Trying transient unit %s: %s", transient, " ".join(command))
        result = _run(
            [
                "systemd-run",
                "--user",
                "--quiet",
                "--collect",
                f"--unit={transient}",
                "--description=Piper text-to-speech server",
                "--",
                *command,
            ]
        )
        if result is not None:
            _LOGGER.info("Started transient unit %s", transient)
            self._server_unit = transient
            return True

        # Someone else won the race: the unit is already running.
        return _run(["systemctl", "--user", "is-active", "--", transient]) is not None

    def _spawn(self, command: Sequence[str]) -> bool:
        """Start the server as a detached child process (no systemd)."""
        log_file = _open_server_log()
        _LOGGER.info("Starting Piper server: %s", " ".join(command))
        try:
            # start_new_session: the server outlives this module, so the next
            # Speech Dispatcher restart finds a warm voice, and Speech
            # Dispatcher's signals do not reach it.
            self._server_process = (
                subprocess.Popen(  # pylint: disable=consider-using-with
                    list(command),
                    stdin=subprocess.DEVNULL,
                    stdout=log_file if log_file is not None else subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            )
            return True
        except OSError as error:
            _LOGGER.error("Failed to start Piper server: %s", error)
            return False
        finally:
            if log_file is not None:
                log_file.close()

    def _wait_for_server(self, cancel: Optional[threading.Event] = None) -> bool:
        deadline = time.monotonic() + self.config.server_timeout
        while time.monotonic() < deadline:
            if self._aborted(cancel):
                return False

            if self._server_is_up():
                return True

            process = self._server_process
            if (process is not None) and (process.poll() is not None):
                _LOGGER.error(
                    "Piper server exited with %s (see %s)",
                    process.returncode,
                    server_log_path(),
                )
                return False

            if (self._server_unit is not None) and _unit_failed(self._server_unit):
                _LOGGER.error(
                    "%s failed to start (journalctl --user -u %s)",
                    self._server_unit,
                    self._server_unit,
                )
                return False

            time.sleep(0.2)

        return False

    # -- main loop --------------------------------------------------------

    def run(self) -> int:
        """Run the module until QUIT or end of input."""
        line = self._read_line()
        if line != "INIT":
            _LOGGER.error("Expected INIT, got %r", line)
            return 3

        self._worker.start()

        # Speech Dispatcher blocks while a module loads, so the server is
        # started in the background: the daemon (and the whole desktop session)
        # must not wait for a model to load. Utterances that arrive before the
        # server is up wait for it in the worker thread instead.
        threading.Thread(
            target=self.ensure_server, name="piper-autostart", daemon=True
        ).start()

        self._writer.write_lines(
            f"299-{MODULE_NAME}: streaming Piper via {self.config.url}",
            "299 OK LOADED SUCCESSFULLY",
        )

        while not self._quit.is_set():
            line = self._read_line()
            if line is None:
                break

            try:
                self._handle(line)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Error handling command %r", line)
                self._writer.write_lines("401 ERROR INTERNAL")

        self.close()
        return 0

    def close(self) -> None:
        self._quit.set()
        self._drain_queue()
        self._interrupt(notify_server=False)
        self._queue.put(None)

    def _read_line(self) -> Optional[str]:
        """Read one LF-terminated line, or None at end of input."""
        data = self._stdin.readline()
        if not data:
            return None

        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace").rstrip("\n")

        return data.rstrip("\n")

    def _read_block(self) -> Optional[List[str]]:
        """Read lines until a line containing only a dot."""
        lines: List[str] = []
        while True:
            line = self._read_line()
            if line is None:
                return None

            if line == ".":
                return lines

            # Dot-stuffing: a leading dot was doubled by the server
            if line.startswith("."):
                line = line[1:]

            lines.append(line)

    def _handle(self, line: str) -> None:
        command = line.strip()
        upper = command.upper()

        if upper == "SPEAK":
            self._cmd_speak()
        elif upper == "CHAR":
            self._cmd_speak(single_line=True, mode="char")
        elif upper == "KEY":
            self._cmd_speak(single_line=True, mode="key")
        elif upper == "SOUND_ICON":
            # No sound icons: let Speech Dispatcher fall back
            block = self._read_block()
            if block is not None:
                self._writer.write_lines("301 ERROR CANT SPEAK")
        elif upper == "STOP":
            self._cmd_stop()
        elif upper == "PAUSE":
            # Piper has no resume position: pausing behaves like stopping.
            self._cmd_stop(pause=True)
        elif upper == "SET":
            self._cmd_settings("203 OK RECEIVING SETTINGS", "203 OK SETTINGS RECEIVED")
        elif upper == "AUDIO":
            self._cmd_audio()
        elif upper == "LOGLEVEL":
            self._cmd_settings(
                "207 OK RECEIVING LOGLEVEL SETTINGS", "203 OK LOGLEVEL SET"
            )
        elif upper.startswith("LIST VOICES"):
            self._cmd_list_voices(command[len("LIST VOICES") :].split())
        elif upper.startswith("DEBUG"):
            self._cmd_debug(command.split())
        elif upper == "QUIT":
            self._writer.write_lines("210 OK QUIT")
            self._quit.set()
            self.close()
        else:
            self._writer.write_lines("300 ERR UNKNOWN COMMAND")

    # -- commands ---------------------------------------------------------

    def _cmd_speak(self, single_line: bool = False, mode: str = "text") -> None:
        self._writer.write_lines("202 OK RECEIVING MESSAGE")
        block = self._read_block()
        if block is None:
            return

        if single_line and (len(block) > 1):
            self._writer.write_lines("305 DATA MORE THAN ONE LINE")
            return

        message = "\n".join(block)
        chunking: Optional[ChunkingConfig] = None
        marks: List[Tuple[int, str]] = []
        if mode == "char":
            # Single characters and key names are short and must stay in one
            # piece: chunking them would be pointless and could split a name.
            text = _char_to_text(message)
            chunking = PROFILES["off"]
        elif mode == "key":
            text = _key_to_text(message)
            chunking = PROFILES["off"]
        else:
            text, marks = parse_ssml(message)

        text = text.strip()
        if not text:
            self._writer.write_lines("301 ERROR CANT SPEAK")
            return

        # Cancel anything queued and stop what is playing: the new message
        # wins. Cancelled messages are still reported as stopped.
        self._cancel_queued()
        self._interrupt()

        # Each utterance carries its own cancellation token, created *before*
        # the acknowledgement: Speech Dispatcher may send STOP as soon as it has
        # the reply, and that STOP must apply to this utterance, not the
        # previous one.
        utterance = Utterance(
            text=text, marks=marks, group=uuid.uuid4().hex, chunking=chunking
        )
        with self._current_lock:
            self._current = utterance

        self._writer.write_lines("200 OK SPEAKING")
        self._queue.put(utterance)

    def _cmd_stop(self, pause: bool = False) -> None:
        # No reply is allowed for STOP/PAUSE: the 703/704 event is the answer.
        _LOGGER.debug("Stop requested (pause=%s)", pause)
        self._cancel_queued(pause=pause)
        self._interrupt(pause=pause)

    def _cmd_settings(self, receiving: str, received: str) -> None:
        self._writer.write_lines(receiving)
        block = self._read_block()
        if block is None:
            return

        error: Optional[str] = None
        for line in block:
            if "=" not in line:
                error = error or "302 ERROR BAD SYNTAX"
                continue

            key, _, value = line.partition("=")
            try:
                self._set_parameter(key.strip().lower(), value.strip())
            except ValueError:
                error = error or "303 ERROR INVALID PARAMETER OR VALUE"

        self._client.config = self._client_config()
        self._writer.write_lines(error or received)

    def _set_parameter(self, key: str, value: str) -> None:
        if key == "rate":
            self._rate = float(value)
        elif key == "volume":
            self._volume = float(value)
        elif key == "voice":
            self._voice_type = value.upper()
        elif key == "language":
            self._language = None if value == "NULL" else value
        elif key == "synthesis_voice":
            self._synthesis_voice = None if value == "NULL" else value
        elif key == "log_level":
            self.config.log_level = int(value)
            logging.getLogger().setLevel(_log_level(int(value)))
        elif key in (
            "pitch",
            "pitch_range",
            "punctuation_mode",
            "spelling_mode",
            "cap_let_recogn",
        ):
            # Not supported by Piper voices; ignored on purpose.
            _LOGGER.debug("Ignoring unsupported parameter %s=%s", key, value)
        else:
            _LOGGER.debug("Unknown parameter %s=%s", key, value)

    def _cmd_audio(self) -> None:
        self._writer.write_lines("207 OK RECEIVING AUDIO SETTINGS")
        block = self._read_block()
        if block is None:
            return

        settings = dict(
            line.partition("=")[::2] for line in block if "=" in line  # type: ignore[misc]
        )
        method = settings.get("audio_output_method", "")

        if method == "server":
            if self.config.audio_output == "server":
                self._server_audio = True
                self._writer.write_lines("203 OK AUDIO INITIALIZED")
            else:
                # Refuse server-side audio: we play the audio ourselves, which
                # lets us drop buffered audio instantly on STOP.
                self._writer.write_lines(
                    "300-piper plays audio itself", "300 MODULE ERROR"
                )

            return

        self._server_audio = False
        self._writer.write_lines("203 OK AUDIO INITIALIZED")

    def _cmd_list_voices(self, arguments: Sequence[str]) -> None:
        voices = self._voice_list()
        if arguments:
            language = arguments[0].lower()
            variant = arguments[1].lower() if len(arguments) > 1 else None
            filtered = [
                voice
                for voice in voices
                if voice[1].lower() == language
                and ((variant is None) or (voice[2].lower() == variant))
            ]
            if not filtered:
                prefix = language.split("-")[0]
                filtered = [
                    voice
                    for voice in voices
                    if voice[1].lower().split("-")[0] == prefix
                    and ((variant is None) or (voice[2].lower() == variant))
                ]

            voices = filtered

        if not voices:
            self._writer.write_lines("304 CANT LIST VOICES")
            return

        self._writer.write_lines(
            *[
                f"200-{name}\t{language}\t{variant}"
                for name, language, variant in voices
            ],
            "200 OK VOICE LIST SENT",
        )

    def _cmd_debug(self, parts: Sequence[str]) -> None:
        if (len(parts) >= 2) and (parts[1].upper() == "ON"):
            path = parts[2] if len(parts) > 2 else None
            if path:
                try:
                    handler = logging.FileHandler(path, encoding="utf-8")
                    handler.setFormatter(
                        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
                    )
                    logging.getLogger().addHandler(handler)
                    logging.getLogger().setLevel(logging.DEBUG)
                except OSError as error:
                    _LOGGER.warning("Cannot open debug file %s: %s", path, error)
                    self._writer.write_lines("303 CANT OPEN CUSTOM DEBUG FILE")
                    return

            self._writer.write_lines("200 OK DEBUGGING ON")
        else:
            logging.getLogger().setLevel(_log_level(self.config.log_level))
            self._writer.write_lines("200 OK DEBUGGING OFF")

    # -- speaking ---------------------------------------------------------

    def _drain_queue(self) -> None:
        """Throw away everything queued (used when shutting down)."""
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                break

    def _cancel_queued(self, pause: bool = False) -> None:
        """Cancel queued messages, but leave them in the queue.

        Every queued message has already been acknowledged with ``200 OK
        SPEAKING``, so Speech Dispatcher waits for a begin/end pair for each of
        them. The worker sends those pairs, in order, when it picks the
        cancelled messages up again.
        """
        pending: List[Utterance] = []
        quit_sentinel = False

        while True:
            try:
                utterance = self._queue.get_nowait()
            except Empty:
                break

            if utterance is None:
                quit_sentinel = True
                continue

            utterance.cancel(pause=pause)
            pending.append(utterance)

        for utterance in pending:
            self._queue.put(utterance)

        if quit_sentinel:
            self._queue.put(None)

    def _interrupt(self, pause: bool = False, notify_server: bool = True) -> None:
        """Stop playback and inference immediately."""
        with self._current_lock:
            current = self._current

        if current is not None:
            current.cancel(pause=pause)

        # Kills the player process, aborts the HTTP streams and tells the
        # server to abandon the inference in progress.
        self._client.stop(notify_server=notify_server)

    def _voice_sample_rate(self) -> int:
        """Sample rate of the voice that is about to be spoken.

        Voices do not share one sample rate (``fr_FR-tom-medium`` is 44.1 kHz,
        ``en_US-kristin-medium`` 22.05 kHz): playing one at the rate of another
        makes speech slow and low-pitched (or fast and high-pitched).
        """
        try:
            return self._client.sample_rate(self._current_voice())
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            _LOGGER.warning("Cannot get the sample rate of the voice: %s", error)
            return self._sample_rate

    def _make_sink(self, sample_rate: int) -> Any:
        if self._server_audio:
            return ServerAudioSink(self._writer, sample_rate)

        return AudioSink(
            PlayerConfig(
                command=self.config.player, latency_ms=self.config.player_latency_ms
            ),
            sample_rate=sample_rate,
        )

    def _speak_loop(self) -> None:
        while not self._quit.is_set():
            utterance = self._queue.get()
            if utterance is None:
                return

            if utterance.is_cancelled:
                # Cancelled before synthesis even started. Speech Dispatcher
                # has already been told "200 OK SPEAKING", so it waits for a
                # begin/end pair no matter what: report an empty message.
                self._begin(utterance)
                self._writer.write_lines(
                    "704 PAUSE" if utterance.paused else "703 STOP"
                )
                continue

            try:
                self._speak(utterance)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Synthesis failed")
                # The server may have died or been restarted: check (and start
                # it again if needed) before the next utterance.
                self.server_lost()
                # 702 END is only valid after 701 BEGIN; without it Speech
                # Dispatcher keeps waiting for the message to start.
                self._begin(utterance)
                self._writer.write_lines("702 END")

    def _begin(self, utterance: Utterance) -> None:
        """Send ``701 BEGIN`` unless this message already started."""
        if utterance.started:
            return

        utterance.started = True
        self._writer.write_lines("701 BEGIN")

    def _speak(self, utterance: Utterance) -> None:
        # First utterance after a cold start: the server may still be loading
        # its model (or not started at all). This also refreshes the sample
        # rate, which the audio sink needs.
        self.ensure_server(cancel=utterance.cancelled)
        if utterance.is_cancelled:
            self._begin(utterance)
            self._writer.write_lines("704 PAUSE" if utterance.paused else "703 STOP")
            return

        marks = list(utterance.marks)
        current_chunk: Optional[TextChunk] = None

        # Clearing the client's stop flag is done here, in the worker, so a STOP
        # that arrives for this utterance can never be lost.
        self._client.reset()
        config = self._client_config()
        if utterance.chunking is not None:
            config = replace(config, chunking=utterance.chunking)

        self._client.config = config
        # The sink is created after the voice is known: its sample rate must be
        # the one of that voice.
        sink = self._make_sink(self._voice_sample_rate())

        for chunk, audio_bytes in self._client.iter_audio(
            utterance.text, group=utterance.group
        ):
            if utterance.is_cancelled:
                break

            self._begin(utterance)

            if (current_chunk is not None) and (chunk is not current_chunk):
                # Everything up to the end of the previous chunk has been
                # handed to the audio output: report the marks it passed.
                marks = self._report_marks(marks, current_chunk.end)

            current_chunk = chunk
            sink.write(audio_bytes)

        if utterance.is_cancelled:
            sink.stop()
            # Even if playback never started, the message was acknowledged and
            # must be closed, or Speech Dispatcher blocks waiting for it.
            self._begin(utterance)
            self._writer.write_lines("704 PAUSE" if utterance.paused else "703 STOP")
            return

        sink.drain()
        # Nothing was produced (e.g. punctuation only): still open the message
        # so the server does not wait forever.
        self._begin(utterance)

        self._report_marks(marks, None)
        self._writer.write_lines("702 END")

    def _report_marks(
        self, marks: List[Tuple[int, str]], up_to: Optional[int]
    ) -> List[Tuple[int, str]]:
        """Emit index marks up to a text offset (all of them if None)."""
        while marks and ((up_to is None) or (marks[0][0] <= up_to)):
            _, name = marks.pop(0)
            self._writer.write_lines(f"700-{name}", "700 INDEX MARK")

        return marks


def _char_to_text(message: str) -> str:
    if message == "space":
        return " "

    return message


def _key_to_text(message: str) -> str:
    if message == "space":
        return "space"

    return message.replace("_", " ")


def _voice_language(name: str, voice_config: Optional[Dict[str, Any]] = None) -> str:
    """Guess a language tag like ``en-US`` from a voice name/config."""
    if voice_config:
        language = voice_config.get("language")
        if isinstance(language, dict):
            code = language.get("code")
            if code:
                return str(code).replace("_", "-")

        espeak = voice_config.get("espeak")
        if isinstance(espeak, dict) and espeak.get("voice"):
            return str(espeak["voice"])

    # en_US-kristin-medium -> en-US
    return name.split("-")[0].replace("_", "-")


def _log_level(log_level: int) -> int:
    if log_level >= 5:
        return logging.DEBUG

    if log_level >= 3:
        return logging.INFO

    if log_level >= 2:
        return logging.WARNING

    return logging.ERROR


def print_service(config_path: Optional[str] = None) -> str:
    """Render a systemd user unit for the server this module would start."""
    config = ModuleConfig.load(config_path) if config_path else default_module_config()
    command = server_command(config) or default_server_command(
        replace(config, default_voice="en_US-kristin-medium")
    )
    assert command is not None

    # systemd wants an absolute ExecStart and does not search the caller's PATH.
    program = shutil.which(command[0])
    if program:
        command = [program, *command[1:]]
    elif not os.path.isabs(command[0]):
        _LOGGER.warning("%s is not in PATH: fix ExecStart by hand", command[0])

    return SERVICE_UNIT.format(command=" ".join(shlex.quote(part) for part in command))


def default_module_config() -> ModuleConfig:
    """The configuration the module uses when installed as documented."""
    return ModuleConfig.load(
        os.path.join(
            os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
            "speech-dispatcher",
            "modules",
            f"{MODULE_NAME}.conf",
        )
    )


def main() -> int:
    """Entry point used by Speech Dispatcher (``sd_piper <config file>``)."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    arguments = sys.argv[1:]
    # Not part of the module protocol: convenience for installation.
    # (Speech Dispatcher only ever passes a configuration file path.)
    if arguments and (arguments[0] in ("--print-config", "-c")):
        sys.stdout.write(EXAMPLE_CONFIG)
        return 0

    if arguments and (arguments[0] == "--print-service"):
        sys.stdout.write(print_service(arguments[1] if len(arguments) > 1 else None))
        return 0

    config_path = arguments[0] if arguments else None
    if config_path and (not os.path.isabs(config_path)):
        config_path = os.path.abspath(config_path)

    config = ModuleConfig.load(config_path)
    _LOGGER.info("Starting %s module (url=%s)", MODULE_NAME, config.url)

    module = PiperSpeechdModule(config)
    try:
        return module.run()
    finally:
        module.close()


if __name__ == "__main__":
    sys.exit(main())
