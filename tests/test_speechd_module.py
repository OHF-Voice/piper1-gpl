"""Tests for the Speech Dispatcher output module.

The module protocol is exercised the way Speech Dispatcher does it: commands on
stdin, replies and events on stdout, LF-terminated.
"""

import http.client
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator, List, Tuple

import pytest

from piper.chunking import ChunkingConfig
from piper.speechd_module import (
    EXAMPLE_CONFIG,
    ModuleConfig,
    PiperSpeechdModule,
    StartLock,
    VoiceEntry,
    default_server_command,
    escape_audio,
    is_local_url,
    parse_ssml,
    print_service,
    server_command,
    split_url,
)

from .stub_server import FR_SAMPLE_RATE, SAMPLE_RATE, StubServer

# A player that consumes audio at (roughly) real time, so that interruption is
# observable in tests.
SLOW_PLAYER = (
    "python3 -c "
    "'import sys,time\n"
    "while sys.stdin.buffer.read(4410):\n"
    "    time.sleep(0.05)'"
)
NULL_PLAYER = "python3 -c 'import sys;sys.stdin.buffer.read()'"


# -----------------------------------------------------------------------------
# SSML and audio encoding
# -----------------------------------------------------------------------------


def test_parse_ssml_plain_text() -> None:
    text, marks = parse_ssml("<speak>Hello world.</speak>")
    assert text == "Hello world."
    assert not marks


def test_parse_ssml_index_marks() -> None:
    text, marks = parse_ssml(
        '<speak>One. <mark name="__spd_0"/>Two. <mark name="__spd_1"/>Three.</speak>'
    )
    assert text == "One. Two. Three."
    assert marks == [(5, "__spd_0"), (10, "__spd_1")]
    for offset, _name in marks:
        assert 0 <= offset <= len(text)


def test_parse_ssml_unescapes_entities() -> None:
    text, _marks = parse_ssml("<speak>a &lt; b &amp; c &gt; d</speak>")
    assert text == "a < b & c > d"


def test_parse_ssml_ignores_unknown_tags() -> None:
    text, _marks = parse_ssml(
        '<speak><prosody rate="fast">Fast</prosody> and slow</speak>'
    )
    assert text == "Fast and slow"


def test_escape_audio_roundtrip() -> None:
    """Audio handed back to Speech Dispatcher is HDLC-escaped."""
    raw = bytes(range(256))
    escaped = escape_audio(raw)
    assert b"\n" not in escaped

    unescaped = bytearray()
    pending = False
    for byte in escaped:
        if pending:
            unescaped.append(byte ^ 0x20)
            pending = False
        elif byte == 0x7D:
            pending = True
        else:
            unescaped.append(byte)

    assert bytes(unescaped) == raw


def test_escape_audio_leaves_clean_audio_untouched() -> None:
    raw = bytes([0x01, 0x02, 0x03])
    assert escape_audio(raw) is raw


# -----------------------------------------------------------------------------
# Configuration file
# -----------------------------------------------------------------------------


def test_module_config_parsing(tmp_path: Path) -> None:
    config_path = tmp_path / "piper.conf"
    config_path.write_text(
        """
# Comment
PiperURL "http://localhost:5123"
PiperAudio server
PiperPlayer "aplay -q -"
PiperChunkProfile instant
PiperChunkMaxWords 4
PiperChunkMinWords 2
PiperChunkMaxChars 200
PiperRateFactor 2.5
PiperPrefetch 3
AddVoice "en-US" "FEMALE1" "en_US-test-medium"
AddVoice "fr-FR" "MALE1"   "fr_FR-test-medium"
DefaultVoice "en_US-test-medium"
""",
        encoding="utf-8",
    )

    config = ModuleConfig.load(str(config_path))
    assert config.url == "http://localhost:5123"
    assert config.audio_output == "server"
    assert config.player == "aplay -q -"
    assert config.chunking.max_words == 4
    assert config.chunking.min_words == 2
    assert config.chunking.max_chars == 200
    assert config.chunking.first_max_words == 2  # from the "instant" profile
    assert config.rate_factor == 2.5
    assert config.prefetch == 3
    assert config.default_voice == "en_US-test-medium"
    assert [voice.name for voice in config.voices] == [
        "en_US-test-medium",
        "fr_FR-test-medium",
    ]


def test_example_config_matches_the_repository_copy() -> None:
    """`sd_piper --print-config` must stay in sync with etc/."""
    repo_config = (
        Path(__file__).parent.parent
        / "etc"
        / "speech-dispatcher"
        / "modules"
        / "piper.conf"
    )
    if not repo_config.exists():
        pytest.skip("not running from a source checkout")

    assert EXAMPLE_CONFIG == repo_config.read_text(encoding="utf-8")


def test_example_config_is_valid(tmp_path: Path) -> None:
    """The shipped example must parse and describe a usable setup."""
    config_path = tmp_path / "piper.conf"
    config_path.write_text(EXAMPLE_CONFIG, encoding="utf-8")

    config = ModuleConfig.load(str(config_path))
    assert config.url.startswith("http")
    assert config.audio_output in ("player", "server")
    assert config.chunking.enabled
    assert config.voices
    assert config.default_voice


def test_module_config_missing_file_uses_defaults() -> None:
    config = ModuleConfig.load("/nonexistent/piper.conf")
    assert config.url
    assert config.audio_output == "player"


# -----------------------------------------------------------------------------
# Starting the server
# -----------------------------------------------------------------------------


def test_autostart_options(tmp_path: Path) -> None:
    config_path = tmp_path / "piper.conf"
    config_path.write_text(
        """
PiperAutostart no
PiperServerManager process
PiperServerService none
PiperServerCommand "python3 -m piper.http_server -m voice.onnx"
PiperServerTimeout 5
""",
        encoding="utf-8",
    )

    config = ModuleConfig.load(str(config_path))
    assert config.autostart == "no"
    assert config.server_manager == "process"
    assert config.server_service == "none"
    assert config.server_timeout == 5.0
    assert server_command(config) == [
        "python3",
        "-m",
        "piper.http_server",
        "-m",
        "voice.onnx",
    ]


def test_server_command_expands_the_home_directory(tmp_path: Path) -> None:
    """Configuration files are not read by a shell, so "~" must be expanded."""
    config_path = tmp_path / "piper.conf"
    config_path.write_text(
        'PiperServerCommand "python3 -m piper.http_server'
        ' -m ~/.piper-voices/en_US-kristin-medium.onnx --data-dir=~/.piper-voices"\n',
        encoding="utf-8",
    )

    command = server_command(ModuleConfig.load(str(config_path)))
    assert command is not None
    home = os.path.expanduser("~")
    assert command[-2:] == [
        f"{home}/.piper-voices/en_US-kristin-medium.onnx",
        f"--data-dir={home}/.piper-voices",
    ]
    assert "~" not in " ".join(command)


@pytest.mark.parametrize(
    "value,expected", [("1", "yes"), ("0", "no"), ("on", "yes"), ("auto", "auto")]
)
def test_autostart_accepts_boolean_values(
    tmp_path: Path, value: str, expected: str
) -> None:
    """`PiperAutostart 1` from older configurations must keep working."""
    config_path = tmp_path / "piper.conf"
    config_path.write_text(f"PiperAutostart {value}\n", encoding="utf-8")
    assert ModuleConfig.load(str(config_path)).autostart == expected


def test_default_autostart_is_enabled_for_a_local_server() -> None:
    config = ModuleConfig()
    assert config.autostart == "auto"
    assert is_local_url(config.url)


@pytest.mark.parametrize(
    "url,local",
    [
        ("http://localhost:5000", True),
        ("http://127.0.0.1:5000", True),
        ("http://[::1]:5000", True),
        ("http://piper.invalid:5000", False),
        ("http://192.168.1.10:5000", False),
    ],
)
def test_is_local_url(url: str, local: bool) -> None:
    assert is_local_url(url) is local


def test_default_server_command_uses_the_configured_voice() -> None:
    config = ModuleConfig(
        url="http://localhost:5123", default_voice="en_US-kristin-medium"
    )
    command = default_server_command(config)
    assert command is not None
    assert command[1:] == [
        "-m",
        "piper.http_server",
        "--host",
        "127.0.0.1",
        "--port",
        "5123",
        "--model",
        "en_US-kristin-medium",
    ]

    # Without DefaultVoice, the first AddVoice entry is used
    config = ModuleConfig(voices=[VoiceEntry("en-US", "FEMALE1", "en_US-test-medium")])
    assert default_server_command(config)[-1] == "en_US-test-medium"  # type: ignore[index]

    # Nothing to start without a voice
    assert default_server_command(ModuleConfig()) is None


def test_print_service_renders_a_runnable_unit(tmp_path: Path) -> None:
    config_path = tmp_path / "piper.conf"
    config_path.write_text(EXAMPLE_CONFIG, encoding="utf-8")

    unit = print_service(str(config_path))
    assert "[Service]" in unit
    assert "WantedBy=default.target" in unit

    exec_start = [
        line[len("ExecStart=") :]
        for line in unit.splitlines()
        if line.startswith("ExecStart=")
    ]
    assert len(exec_start) == 1
    assert "piper.http_server" in exec_start[0]
    assert "en_US-kristin-medium" in exec_start[0]
    # systemd neither expands "~" nor searches PATH
    assert os.path.isabs(exec_start[0].split()[0])
    assert "~" not in exec_start[0]

    # A server that cannot start must back off instead of looping
    settings = dict(
        line.split("=", 1)
        for line in unit.splitlines()
        if ("=" in line) and (not line.startswith("#"))
    )
    assert settings["Restart"] == "on-failure"
    assert int(settings["RestartSec"]) >= 2
    assert int(settings["RestartMaxDelaySec"]) > int(settings["RestartSec"])
    assert int(settings["RestartSteps"]) > 1
    assert int(settings["StartLimitBurst"]) >= 3


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stub_server_command(port: int, startup_delay: float = 0.0) -> str:
    stub = Path(__file__).parent / "stub_server.py"
    return (
        f"{sys.executable} {stub} --port {port} --startup-delay {startup_delay}"
        " --lifetime 60 --model ignored"
    )


@pytest.fixture(name="autostart_config")
def autostart_config_fixture() -> Iterator[ModuleConfig]:
    """A module configuration that starts a stub server on a free port."""
    port = _free_port()
    config = ModuleConfig(
        url=f"http://127.0.0.1:{port}",
        player=NULL_PLAYER,
        voices=[VoiceEntry("en-US", "FEMALE1", "en_US-test-medium")],
        chunking=ChunkingConfig(max_words=3, first_max_words=2, min_words=1),
        # systemd is not available (or wanted) in a test environment
        server_manager="process",
        server_service="none",
        server_command=_stub_server_command(port),
        server_timeout=20.0,
    )
    try:
        yield config
    finally:
        _kill_server(config)


def _kill_server(config: ModuleConfig) -> None:
    """Stop a stub server started by the module (it also exits on its own)."""
    host, port = split_url(config.url)
    try:
        connection = http.client.HTTPConnection(host, port, timeout=2.0)
        connection.request("POST", "/shutdown")
        connection.getresponse().read()
        connection.close()
    except OSError:
        pass


def test_autostart_starts_the_server_on_demand(autostart_config: ModuleConfig) -> None:
    """The first utterance must start the server and be spoken."""
    harness = ModuleHarness(autostart_config).start()
    try:
        harness.init()
        harness.clear()
        harness.speak("<speak>The server was not running.</speak>")
        harness.wait_for("702 END", timeout=30)
        assert _check_event_pairing(harness.replies()) == 1
    finally:
        harness.close()


def test_init_does_not_wait_for_the_server(autostart_config: ModuleConfig) -> None:
    """Speech Dispatcher blocks while a module loads: INIT must be fast."""
    autostart_config.server_command = _stub_server_command(
        split_url(autostart_config.url)[1], startup_delay=3.0
    )

    harness = ModuleHarness(autostart_config).start()
    try:
        start = time.monotonic()
        harness.send("INIT")
        harness.wait_for("299 OK LOADED SUCCESSFULLY", timeout=10)
        assert (time.monotonic() - start) < 2.0

        # The utterance itself waits for the server that is still starting
        harness.send("AUDIO", "audio_output_method=alsa", ".")
        harness.wait_for("203 OK AUDIO INITIALIZED")
        harness.clear()
        harness.speak("<speak>Spoken once the server is up.</speak>")
        harness.wait_for("702 END", timeout=30)
    finally:
        harness.close()


def test_stop_while_the_server_is_starting(autostart_config: ModuleConfig) -> None:
    """STOP must interrupt an utterance that is waiting for the server."""
    autostart_config.server_command = _stub_server_command(
        split_url(autostart_config.url)[1], startup_delay=10.0
    )

    harness = ModuleHarness(autostart_config).start()
    try:
        harness.init()
        harness.clear()
        harness.speak("<speak>Nobody is listening yet.</speak>")
        harness.wait_for("200 OK SPEAKING")

        start = time.monotonic()
        harness.send("STOP")
        harness.wait_for("703 STOP", timeout=5)
        assert (time.monotonic() - start) < 2.0
        assert _check_event_pairing(harness.replies()) == 1
    finally:
        harness.close()


def test_autostart_disabled_starts_nothing(autostart_config: ModuleConfig) -> None:
    autostart_config.autostart = "no"
    module = PiperSpeechdModule(autostart_config)
    try:
        assert module.ensure_server() is False
    finally:
        module.close()

    _, port = split_url(autostart_config.url)
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0, "a server was started"


def test_remote_servers_are_never_started() -> None:
    config = ModuleConfig(url="http://piper.invalid:5000", autostart="yes")
    module = PiperSpeechdModule(config)
    try:
        assert module.ensure_server() is False
    finally:
        module.close()


def test_only_one_server_is_started_when_the_lock_is_taken(
    autostart_config: ModuleConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second module must wait for the first one instead of starting a server."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    _, port = split_url(autostart_config.url)
    autostart_config.server_timeout = 2.0

    module = PiperSpeechdModule(autostart_config)
    holder = StartLock(port)
    with holder as owned:
        assert owned
        try:
            # The lock is held (as if another module were starting the server),
            # so this one only waits, and times out because nothing comes up.
            assert module.ensure_server() is False
        finally:
            module.close()

    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0, "a second server was started"


def test_a_running_server_is_reused(server: StubServer) -> None:
    """No process is started when the configured server already answers."""
    config = make_config(
        server,
        server_manager="process",
        server_service="none",
        server_command="false",  # would fail if it were ever run
    )
    module = PiperSpeechdModule(config)
    try:
        assert module.ensure_server() is True
        assert module.ensure_server() is True
    finally:
        module.close()


# -----------------------------------------------------------------------------
# Protocol
# -----------------------------------------------------------------------------


class ModuleHarness:
    """Runs the module in a thread and speaks its protocol over pipes."""

    def __init__(self, config: ModuleConfig) -> None:
        stdin_read, self._stdin_write = os.pipe()
        self._stdout_read, stdout_write = os.pipe()

        self._stdin = os.fdopen(self._stdin_write, "wb", buffering=0)
        self._stdout = os.fdopen(self._stdout_read, "rb", buffering=0)

        self.module = PiperSpeechdModule(
            config,
            stdin=os.fdopen(stdin_read, "rb", buffering=0),
            stdout=os.fdopen(stdout_write, "wb", buffering=0),
        )
        self.output = bytearray()
        self.lines: List[str] = []
        self._lock = threading.Lock()

        self._thread = threading.Thread(target=self.module.run, daemon=True)
        self._reader = threading.Thread(target=self._read, daemon=True)

    def start(self) -> "ModuleHarness":
        self._thread.start()
        self._reader.start()
        return self

    def _read(self) -> None:
        while True:
            data = self._stdout.read(1)
            if not data:
                return

            with self._lock:
                self.output.extend(data)
                if data == b"\n":
                    line = bytes(self.output).split(b"\n")[-2]
                    self.lines.append(line.decode("utf-8", errors="replace"))

    def send(self, *lines: str) -> None:
        self._stdin.write("".join(f"{line}\n" for line in lines).encode("utf-8"))

    def wait_for(self, pattern: str, timeout: float = 10.0) -> str:
        """Wait for a line matching a regular expression."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for line in self.lines:
                    if re.fullmatch(pattern, line):
                        return line

            time.sleep(0.01)

        raise AssertionError(f"Timed out waiting for {pattern!r}, got {self.lines}")

    def replies(self) -> List[str]:
        with self._lock:
            return list(self.lines)

    def clear(self) -> None:
        with self._lock:
            self.lines.clear()

    def init(self, audio: str = "alsa") -> None:
        self.send("INIT")
        self.wait_for("299 OK LOADED SUCCESSFULLY")
        self.send("AUDIO", f"audio_output_method={audio}", ".")
        self.wait_for("203 OK AUDIO INITIALIZED")

    def speak(self, ssml: str) -> None:
        self.send("SPEAK", ssml, ".")

    def close(self) -> None:
        try:
            self.send("QUIT")
            self.wait_for("210 OK QUIT", timeout=5)
        except (AssertionError, OSError):
            pass

        self.module.close()


@pytest.fixture(name="server")
def server_fixture() -> Iterator[StubServer]:
    with StubServer() as server:
        yield server


def make_config(server: StubServer, **kwargs: Any) -> ModuleConfig:
    config = ModuleConfig(
        url=server.url,
        player=NULL_PLAYER,
        voices=[VoiceEntry("en-US", "FEMALE1", "en_US-test-medium")],
        chunking=ChunkingConfig(max_words=3, first_max_words=2, min_words=1),
    )
    for name, value in kwargs.items():
        setattr(config, name, value)

    return config


@pytest.fixture(name="module")
def module_fixture(server: StubServer) -> Iterator[ModuleHarness]:
    harness = ModuleHarness(make_config(server)).start()
    try:
        yield harness
    finally:
        harness.close()


def test_init_handshake(module: ModuleHarness) -> None:
    module.send("INIT")
    module.wait_for("299 OK LOADED SUCCESSFULLY")
    replies = module.replies()
    # Multi-line replies use "-" as the fourth character
    assert replies[0].startswith("299-")
    assert len(replies[0]) > 4


def test_unknown_command(module: ModuleHarness) -> None:
    module.init()
    module.send("NONSENSE")
    module.wait_for("300 ERR UNKNOWN COMMAND")


def test_audio_negotiation_refuses_server_audio_by_default(
    module: ModuleHarness,
) -> None:
    """In player mode the module plays audio itself, so it must refuse."""
    module.send("INIT")
    module.wait_for("299 OK LOADED SUCCESSFULLY")
    module.send("AUDIO", "audio_output_method=server", ".")
    module.wait_for("300 MODULE ERROR")

    module.send("AUDIO", "audio_output_method=alsa", "audio_alsa_device=default", ".")
    module.wait_for("203 OK AUDIO INITIALIZED")


def test_settings_and_loglevel(module: ModuleHarness) -> None:
    module.init()
    module.send(
        "SET",
        "pitch=0",
        "pitch_range=0",
        "rate=50",
        "volume=100",
        "punctuation_mode=none",
        "spelling_mode=off",
        "cap_let_recogn=none",
        "voice=female1",
        "language=en-US",
        "synthesis_voice=NULL",
        ".",
    )
    module.wait_for("203 OK SETTINGS RECEIVED")

    module.send("LOGLEVEL", "log_level=3", ".")
    module.wait_for("203 OK LOGLEVEL SET")


def test_settings_bad_syntax(module: ModuleHarness) -> None:
    module.init()
    module.send("SET", "this-is-not-a-parameter", ".")
    module.wait_for("302 ERROR BAD SYNTAX")


def test_settings_invalid_value(module: ModuleHarness) -> None:
    module.init()
    module.send("SET", "rate=fast", ".")
    module.wait_for("303 ERROR INVALID PARAMETER OR VALUE")


def test_rate_changes_length_scale(server: StubServer, module: ModuleHarness) -> None:
    module.init()
    module.send("SET", "rate=100", ".")
    module.wait_for("203 OK SETTINGS RECEIVED")
    module.speak("<speak>Hello.</speak>")
    module.wait_for("702 END")

    assert server.requests[0]["length_scale"] < 1.0


def test_voice_selection_by_language(server: StubServer) -> None:
    config = make_config(
        server,
        voices=[
            VoiceEntry("en-US", "FEMALE1", "en_US-test-medium"),
            VoiceEntry("fr-FR", "FEMALE1", "fr_FR-test-medium"),
        ],
    )
    harness = ModuleHarness(config).start()
    try:
        harness.init()
        harness.send("SET", "voice=female1", "language=fr-FR", ".")
        harness.wait_for("203 OK SETTINGS RECEIVED")
        harness.speak("<speak>Bonjour.</speak>")
        harness.wait_for("702 END")

        assert server.requests[0]["voice"] == "fr_FR-test-medium"
    finally:
        harness.close()


def test_synthesis_voice_overrides_symbolic_voice(
    server: StubServer, module: ModuleHarness
) -> None:
    module.init()
    module.send("SET", "voice=female1", "synthesis_voice=fr_FR-test-medium", ".")
    module.wait_for("203 OK SETTINGS RECEIVED")
    module.speak("<speak>Bonjour.</speak>")
    module.wait_for("702 END")

    assert server.requests[0]["voice"] == "fr_FR-test-medium"


def test_list_voices(module: ModuleHarness) -> None:
    module.init()
    module.send("LIST VOICES")
    module.wait_for("200 OK VOICE LIST SENT")

    voice_lines = [line for line in module.replies() if line.startswith("200-")]
    assert voice_lines
    for line in voice_lines:
        # name TAB language TAB variant
        assert len(line[4:].split("\t")) == 3
        assert len(line) > 4


def test_list_voices_with_language_filter(module: ModuleHarness) -> None:
    module.init()
    module.send("LIST VOICES fr-FR")
    module.wait_for("200 OK VOICE LIST SENT")
    assert any("fr_FR-test-medium" in line for line in module.replies())


def test_list_voices_unknown_language(module: ModuleHarness) -> None:
    module.init()
    module.send("LIST VOICES xx-XX")
    module.wait_for("304 CANT LIST VOICES")


def test_speak_event_sequence(server: StubServer, module: ModuleHarness) -> None:
    module.init()
    module.clear()
    module.speak('<speak>One two. <mark name="__spd_0"/>Three four five.</speak>')
    module.wait_for("702 END")

    events = [line for line in module.replies() if line[:1] in ("2", "7")]
    assert events[0] == "202 OK RECEIVING MESSAGE"
    assert events[1] == "200 OK SPEAKING"
    assert events[2] == "701 BEGIN"
    assert events[-1] == "702 END"
    assert "700 INDEX MARK" in events
    assert events.index("700-__spd_0") < events.index("702 END")

    # Text was chunked before being sent
    assert len(server.requests) > 1


def test_empty_message_is_refused(module: ModuleHarness) -> None:
    module.init()
    module.speak("<speak></speak>")
    module.wait_for("301 ERROR CANT SPEAK")


def test_char_and_key(server: StubServer, module: ModuleHarness) -> None:
    module.init()
    module.send("CHAR", "space", ".")
    module.wait_for("301 ERROR CANT SPEAK")  # a space alone has nothing to say

    module.clear()
    module.send("CHAR", "a", ".")
    module.wait_for("702 END")
    assert server.texts()[-1] == "a"

    module.clear()
    module.send("KEY", "control_alt_delete", ".")
    module.wait_for("702 END")
    # Keys and characters are never split into chunks
    assert server.texts()[-1] == "control alt delete"


def test_char_rejects_multiple_lines(module: ModuleHarness) -> None:
    module.init()
    module.send("CHAR", "a", "b", ".")
    module.wait_for("305 DATA MORE THAN ONE LINE")


def test_sound_icon_is_refused(module: ModuleHarness) -> None:
    module.init()
    module.send("SOUND_ICON", "bell", ".")
    module.wait_for("301 ERROR CANT SPEAK")


def test_dot_stuffing_is_undone(server: StubServer, module: ModuleHarness) -> None:
    module.init()
    # Speech Dispatcher doubles a leading dot
    module.send("SPEAK", "<speak>", "..hidden dot</speak>", ".")
    module.wait_for("702 END")
    assert any(".hidden dot" in text for text in server.texts())


def test_stop_interrupts_and_reports_stop(server: StubServer) -> None:
    harness = ModuleHarness(make_config(server, player=SLOW_PLAYER)).start()
    try:
        harness.init()
        harness.clear()
        harness.speak("<speak>" + " ".join(["word"] * 60) + ".</speak>")
        harness.wait_for("701 BEGIN")

        time.sleep(0.2)
        start = time.monotonic()
        harness.send("STOP")
        harness.wait_for("703 STOP", timeout=5)
        stop_seconds = time.monotonic() - start

        # Interruption must be immediate, not "at the end of the utterance"
        assert stop_seconds < 2.0
        assert server.stops, "the server was not told to abandon synthesis"

        # No event may follow the terminating event
        replies = harness.replies()
        assert replies[-1] == "703 STOP"
        assert "702 END" not in replies

        # Speaking again works right away: nothing was restarted
        harness.clear()
        harness.speak("<speak>Next message.</speak>")
        harness.wait_for("702 END", timeout=10)
    finally:
        harness.close()


def test_stop_with_nothing_playing_is_silent(module: ModuleHarness) -> None:
    """STOP must never produce a reply of its own."""
    module.init()
    module.clear()
    module.send("STOP")
    time.sleep(0.3)
    assert module.replies() == []


def _check_event_pairing(replies: List[str]) -> int:
    """Check begin/end pairing and return the number of finished messages.

    Speech Dispatcher blocks forever if a message it acknowledged with "200 OK
    SPEAKING" is never opened with 701 and closed with 702/703/704.
    """
    finished = 0
    open_message = False

    for line in replies:
        if line == "701 BEGIN":
            assert not open_message, f"701 BEGIN inside a message: {replies}"
            open_message = True
        elif line in ("702 END", "703 STOP", "704 PAUSE"):
            assert open_message, f"{line} without 701 BEGIN: {replies}"
            open_message = False
            finished += 1

    assert not open_message, f"message left open: {replies}"
    return finished


def test_stop_before_playback_starts_still_reports_events(server: StubServer) -> None:
    """STOP right after SPEAK must still produce a begin/end pair."""
    harness = ModuleHarness(make_config(server, player=SLOW_PLAYER)).start()
    try:
        harness.init()
        harness.clear()
        harness.speak("<speak>" + " ".join(["word"] * 60) + ".</speak>")
        harness.wait_for("200 OK SPEAKING")
        harness.send("STOP")
        harness.wait_for("703 STOP", timeout=5)

        replies = harness.replies()
        assert _check_event_pairing(replies) == 1
        assert "702 END" not in replies
    finally:
        harness.close()


def test_preempted_messages_are_all_terminated(server: StubServer) -> None:
    """Bursts of messages (the screen reader case) must stay in sync.

    Every acknowledged message needs its own begin/end pair, including the ones
    that never reach the audio output.
    """
    harness = ModuleHarness(make_config(server, player=SLOW_PLAYER)).start()
    try:
        harness.init()
        harness.clear()

        for index in range(6):
            harness.speak(f"<speak>message number {index} with a few words.</speak>")

        harness.send("STOP")

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if _check_event_pairing(harness.replies()) == 6:
                break

            time.sleep(0.05)

        replies = harness.replies()
        assert replies.count("200 OK SPEAKING") == 6
        assert _check_event_pairing(replies) == 6
    finally:
        harness.close()


def test_pause_reports_pause(server: StubServer) -> None:
    harness = ModuleHarness(make_config(server, player=SLOW_PLAYER)).start()
    try:
        harness.init()
        harness.clear()
        harness.speak("<speak>" + " ".join(["word"] * 60) + ".</speak>")
        harness.wait_for("701 BEGIN")
        time.sleep(0.2)
        harness.send("PAUSE")
        harness.wait_for("704 PAUSE", timeout=5)
    finally:
        harness.close()


def test_new_message_preempts_the_previous_one(server: StubServer) -> None:
    """This is the screen reader case: the pointer moved to another area."""
    harness = ModuleHarness(make_config(server, player=SLOW_PLAYER)).start()
    try:
        harness.init()
        harness.clear()
        harness.speak("<speak>" + " ".join(["first"] * 60) + ".</speak>")
        harness.wait_for("701 BEGIN")
        time.sleep(0.2)

        harness.speak("<speak>Second area.</speak>")
        harness.wait_for("703 STOP", timeout=5)
        harness.wait_for("702 END", timeout=10)

        assert any("Second area." in text for text in server.texts())
    finally:
        harness.close()


def test_server_audio_mode_sends_audio_blocks(server: StubServer) -> None:
    """In server audio mode, PCM is handed back to Speech Dispatcher."""
    harness = ModuleHarness(make_config(server, audio_output="server")).start()
    try:
        harness.send("INIT")
        harness.wait_for("299 OK LOADED SUCCESSFULLY")
        harness.send("AUDIO", "audio_output_method=server", ".")
        harness.wait_for("203 OK AUDIO INITIALIZED")

        harness.speak("<speak>Server audio.</speak>")
        harness.wait_for("702 END")

        blocks = _parse_audio_blocks(bytes(harness.output))
        assert blocks
        for sample_rate, num_samples, audio in blocks:
            assert sample_rate == SAMPLE_RATE
            assert len(audio) == num_samples * 2
    finally:
        harness.close()


def test_audio_uses_the_sample_rate_of_the_selected_voice(server: StubServer) -> None:
    """Voices have different sample rates: playing at the wrong one slows speech."""
    config = make_config(
        server,
        audio_output="server",
        voices=[
            VoiceEntry("en-US", "FEMALE1", "en_US-test-medium"),
            VoiceEntry("fr-FR", "FEMALE1", "fr_FR-test-medium"),
        ],
    )
    harness = ModuleHarness(config).start()
    try:
        harness.send("INIT")
        harness.wait_for("299 OK LOADED SUCCESSFULLY")
        harness.send("AUDIO", "audio_output_method=server", ".")
        harness.wait_for("203 OK AUDIO INITIALIZED")

        harness.send("SET", "voice=female1", "language=fr-FR", ".")
        harness.wait_for("203 OK SETTINGS RECEIVED")
        harness.speak("<speak>Bonjour.</speak>")
        harness.wait_for("702 END")

        assert server.texts()[-1].startswith("Bonjour")
        blocks = _parse_audio_blocks(bytes(harness.output))
        assert blocks
        assert {sample_rate for sample_rate, _samples, _audio in blocks} == {
            FR_SAMPLE_RATE
        }
    finally:
        harness.close()


def _parse_audio_blocks(data: bytes) -> List[Tuple[int, int, bytes]]:
    """Decode 705 AUDIO blocks the way Speech Dispatcher does."""
    blocks: List[Tuple[int, int, bytes]] = []
    position = 0
    while True:
        start = data.find(b"705-bits=16\n", position)
        if start < 0:
            return blocks

        marker = data.find(b"705-AUDIO\0", start)
        end = data.find(b"\n705 AUDIO\n", marker)
        assert marker > 0 and end > 0

        header = data[start:marker].decode("utf-8")
        sample_rate = int(re.search(r"sample_rate=(\d+)", header).group(1))  # type: ignore[union-attr]
        num_samples = int(re.search(r"num_samples=(\d+)", header).group(1))  # type: ignore[union-attr]
        assert "big_endian=0" in header
        assert "num_channels=1" in header

        payload = data[marker + len(b"705-AUDIO\0") : end]
        audio = bytearray()
        pending = False
        for byte in payload:
            if pending:
                audio.append(byte ^ 0x20)
                pending = False
            elif byte == 0x7D:
                pending = True
            else:
                audio.append(byte)

        blocks.append((sample_rate, num_samples, bytes(audio)))
        position = end + 1


def test_quit_exits_cleanly(server: StubServer) -> None:
    harness = ModuleHarness(make_config(server)).start()
    harness.init()
    harness.send("QUIT")
    harness.wait_for("210 OK QUIT")


def test_module_survives_a_dead_server(tmp_path: Path) -> None:
    """A missing server must not prevent the module from loading."""
    config = ModuleConfig(url="http://127.0.0.1:1", player=NULL_PLAYER)
    harness = ModuleHarness(config).start()
    try:
        harness.send("INIT")
        harness.wait_for("299 OK LOADED SUCCESSFULLY", timeout=30)

        # LIST VOICES must still return at least one voice
        harness.send("LIST VOICES")
        harness.wait_for("200 OK VOICE LIST SENT", timeout=30)

        # And a failed synthesis must still open and terminate the message
        harness.send("AUDIO", "audio_output_method=alsa", ".")
        harness.clear()
        harness.speak("<speak>Nobody can hear this.</speak>")
        harness.wait_for("702 END", timeout=30)

        replies = harness.replies()
        assert _check_event_pairing(replies) == 1
        assert replies.index("701 BEGIN") < replies.index("702 END")
    finally:
        harness.close()
